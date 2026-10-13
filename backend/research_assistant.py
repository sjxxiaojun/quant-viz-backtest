"""Read-only optional model analysis. Suggestions never execute actions."""
import json
import os
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from experiment_service import ParameterCandidate
from research_metrics import metric_view


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_ids: list[str] = Field(min_length=1, max_length=4)
    use_external: bool = False


class ExperimentProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: str
    changes: ParameterCandidate
    reason: str = Field(max_length=1000)


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: Literal['local', 'external', 'local_fallback'] = 'local'
    job_ids: list[str]
    summary: str = Field(max_length=5000)
    observations: list[str] = Field(default_factory=list, max_length=12)
    proposals: list[ExperimentProposal] = Field(default_factory=list, max_length=4)
    error: str | None = None


def result_context(job):
    result = job['result']
    if job['kind'] == 'experiment':
        evidence = result['test_result']
        parameters = result['request']['base']
    elif job['kind'] == 'backtest':
        evidence = result
        parameters = job['request']
    else:
        evidence = result
        parameters = job['request']
    return {'job_id': job['job_id'], 'kind': job['kind'], 'parameters': parameters,
            'metrics': evidence.get('metrics') or metric_view(evidence),
            'data_as_of': evidence.get('data_as_of'), 'data_snapshot_id': evidence.get('data_snapshot_id'),
            'quality_notes': evidence.get('quality_notes', []),
            'walk_forward': result.get('summary', {}).get('walk_forward'),
            'comparisons': {key: metric_view(value) for key, value in result.items()
                            if job['kind'] == 'compare' and isinstance(value, dict) and 'summary' in value}}


def analyze(jobs, transport, use_external=False):
    contexts = [result_context(job) for job in jobs]
    notes = []
    for context in contexts:
        metric = context['metrics']
        net = metric.get('net_return')
        drawdown = metric.get('max_drawdown')
        note = f"任务 {context['job_id'][:8]}："
        note += f"扣成本收益 {net:.2%}；" if isinstance(net, (int, float)) else '收益指标未提供；'
        note += f"最大回撤 {drawdown:.2%}。" if isinstance(drawdown, (int, float)) else '回撤指标未提供。'
        notes.append(note)
        if metric.get('benchmark_return') is None:
            notes.append('该结果没有可用的基准行情，不能将基准缺失解释为零收益。')
    local = AnalysisResponse(job_ids=[j['job_id'] for j in jobs],
        summary='基于已保存结果的本地分析；收益、成本与风险应同时评估。', observations=notes[:12])
    endpoint = os.getenv('QUANT_AI_ENDPOINT', '').strip()
    if not use_external:
        return local
    if not endpoint:
        return local.model_copy(update={'source': 'local_fallback', 'error': '未配置模型接口，已返回本地分析。'})
    instructions = ('只分析用户选择的已保存结果。返回 JSON，字段 summary、observations、proposals。'
        '每个 proposal 字段 job_id、changes、reason；changes 仅含 max_positions、stop_loss、take_profit、max_hold_days、weight_mode。'
        '只建议参数实验，不能执行任务、交易、切换模型或修改配置。解释必须引用给定任务标识，不能编造指标或保证收益。')
    context = {'instructions': instructions, 'research_results': contexts}
    compatible = os.getenv('QUANT_AI_OPENAI_COMPATIBLE', '').lower() in {'1', 'true', 'yes'}
    payload = {'context': context, 'response_format': 'json'}
    if compatible:
        payload = {'model': os.getenv('QUANT_AI_MODEL', '').strip(),
            'messages': [{'role': 'system', 'content': instructions}, {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}],
            'response_format': {'type': 'json_object'}}
        if not payload['model']:
            return local.model_copy(update={'source': 'local_fallback', 'error': '兼容接口未配置 QUANT_AI_MODEL。'})
    key = os.getenv('QUANT_AI_MODEL_API_KEY', os.getenv('QUANT_AI_API_KEY', '')).strip()
    try:
        raw = transport._post_json(endpoint, key, payload)
        if len(raw) > 100000:
            raise ValueError('模型响应超过大小限制')
        decoded = json.loads(raw)
        if compatible:
            decoded = json.loads(decoded['choices'][0]['message']['content'])
        response = AnalysisResponse.model_validate({**decoded, 'source': 'external', 'job_ids': local.job_ids})
        allowed = {j['job_id'] for j in jobs if j['kind'] in {'backtest', 'experiment'}}
        if any(p.job_id not in allowed for p in response.proposals):
            raise ValueError('建议引用了未选择或不支持参数实验的任务')
        return response
    except Exception:
        # Do not return provider bodies/credentials in user-facing errors.
        return local.model_copy(update={'source': 'local_fallback', 'error': '模型调用或响应校验失败，已返回本地分析。'})
