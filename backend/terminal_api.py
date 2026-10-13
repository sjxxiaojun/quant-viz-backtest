"""Parameter experiments, exact replay and opt-in result analysis."""
import os
from fastapi import APIRouter, HTTPException, Request
from api_models import BacktestJobSubmitResponse
from experiment_service import ExperimentRequest
from research_assistant import AnalysisRequest, AnalysisResponse, analyze
from research_metrics import load_replay_context, validate_replay_strategy


def make_terminal_router(api):
    router = APIRouter()

    @router.post('/api/experiments/jobs', response_model=BacktestJobSubmitResponse)
    def submit_experiment(req: ExperimentRequest, request: Request):
        api._require_local_request(request)
        if api.strategy_version_store.resolve_strategy_spec(req.base.factor) is None:
            raise HTTPException(422, '未知策略')
        try:
            return {'job_id': api.job_queue.submit('experiment', req.model_dump())}
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from exc

    @router.post('/api/research/jobs/{job_id}/replay', response_model=BacktestJobSubmitResponse)
    def replay(job_id: str, request: Request):
        api._require_local_request(request)
        job = api.job_store.get(job_id)
        if not job:
            raise HTTPException(404, '任务不存在')
        if job['status'] != 'succeeded' or job['kind'] not in {'backtest', 'experiment'}:
            raise HTTPException(409, '仅完成的回测与参数实验支持精确快照重放')
        try:
            validate_replay_strategy(api, job['result'])
            load_replay_context(job['result']['data_snapshot_id'])
            config = {**job['request'], '_replay_source_job': job_id}
            return {'job_id': api.job_queue.submit(job['kind'], config)}
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get('/api/research/assistant/status')
    def assistant_status():
        return {'configured': bool(os.getenv('QUANT_AI_ENDPOINT', '').strip()), 'enabled_by_default': False}

    @router.post('/api/research/analysis', response_model=AnalysisResponse)
    def analysis(req: AnalysisRequest, request: Request):
        api._require_local_request(request)
        jobs = [api.job_store.get(job_id) for job_id in req.job_ids]
        if any(job is None for job in jobs):
            raise HTTPException(404, '任务不存在')
        if any(job['status'] != 'succeeded' for job in jobs):
            raise HTTPException(409, '请选择完成的研究任务')
        return analyze(jobs, api.ai_automation_service, req.use_external)

    return router
