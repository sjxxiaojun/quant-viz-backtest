"""Bounded parameter search; held-out test results never select a candidate."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from api_models import BacktestRequest
from job_service import report_stage
from research_contracts import persist_snapshot, snapshot_fingerprint
from research_metrics import metric_view, save_replay_context, strategy_identity, code_fingerprint, runtime_versions


class ParameterCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_positions: int | None = Field(None, ge=1, le=50)
    stop_loss: float | None = Field(None, gt=-1, lt=0)
    take_profit: float | None = Field(None, gt=0, le=10)
    max_hold_days: int | None = Field(None, ge=1, le=260)
    weight_mode: Literal['equal', 'score'] | None = None


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base: BacktestRequest
    candidates: list[ParameterCandidate] = Field(min_length=1, max_length=12)


def freeze_market(api, req):
    symbols, universe, warmup = api.prepare_backtest_universe(req)
    frame, sources = api.data_manager.get_stock_pool_data(
        symbols, warmup, req.end_date, allow_mock=req.allow_mock,
        allow_late_start=bool(universe.get('allow_late_start')))
    if len(frame) > api.BACKTEST_MAX_ROWS:
        raise ValueError('实验行情超过行预算，请减少标的或区间。')
    frame = api.execution_data_service.prepare(frame, allow_approximate=req.price_mode == 'approximate_adjusted' or req.allow_mock)
    try:
        benchmark, _ = api.data_manager.get_stock_data('510300', req.start_date, req.end_date, allow_mock=False)
    except api.DataFetchError:
        benchmark = None
    snapshot = persist_snapshot(frame, req.model_dump(), {**universe, 'symbols': symbols, 'benchmark_fingerprint': snapshot_fingerprint(benchmark, {}), 'replay_code': code_fingerprint(), 'replay_runtime': runtime_versions()})
    save_replay_context(snapshot, symbols, universe, warmup, sources, benchmark)
    return {'symbols': symbols, 'universe': universe, 'warmup_start': warmup,
            'sources': sources, 'frame': frame, 'benchmark': benchmark, 'snapshot_id': snapshot}


def run_experiment(api, request: ExperimentRequest, prepared=None):
    base = request.base
    spec = api.strategy_version_store.resolve_strategy_spec(base.factor)
    if spec is None:
        raise ValueError(f'未知策略：{base.factor}')
    report_stage('冻结参数实验行情')
    market = prepared or freeze_market(api, base)
    market = {**market, 'strategy_spec': spec, 'strategy_identity': strategy_identity(api.strategy_version_store, base.factor, spec)}
    dates = sorted(market['frame'].loc[market['frame'].date.between(base.start_date, base.end_date), 'date'].unique())
    if len(dates) < 60:
        raise ValueError('参数实验至少需要60个交易日；无法完成样本外评估。')
    valid_start, valid_end = dates[int(len(dates)*.6)], dates[int(len(dates)*.8)-1]
    test_start, test_end = dates[int(len(dates)*.8)], dates[-1]
    rows = []
    # Every signal calculation receives only data available by validation end.
    validation_market = {**market, 'frame': market['frame'][market['frame'].date <= valid_end].copy()}
    for index, candidate in enumerate(request.candidates):
        report_stage(f'验证参数 {index+1}/{len(request.candidates)}')
        config = {**base.model_dump(), **candidate.model_dump(exclude_none=True), 'start_date': valid_start, 'end_date': valid_end}
        req = BacktestRequest(**config)
        result = api.execute_backtest(req, allow_mock=req.allow_mock, prepared=validation_market)
        rows.append({'candidate_id': index, 'changes': candidate.model_dump(exclude_none=True),
                     'metrics': metric_view(result), 'result': result})
    ranked = sorted(rows, key=lambda row: (-row['metrics']['net_return'], row['candidate_id']))
    winner = ranked[0]
    report_stage('仅评估胜出配置的独立测试期')
    test_req = BacktestRequest(**{**base.model_dump(), **winner['changes'], 'start_date': test_start, 'end_date': test_end})
    test_result = api.execute_backtest(test_req, allow_mock=test_req.allow_mock, prepared=market)
    return {
        'kind': 'experiment', 'data_snapshot_id': market['snapshot_id'],
        'request': request.model_dump(), 'provenance': test_result['provenance'],
        'selection_metric': 'validation_net_return_after_cost',
        'split': {'training_end': dates[int(len(dates)*.6)-1], 'validation_start': valid_start,
                  'validation_end': valid_end, 'test_start': test_start, 'test_end': test_end},
        'winner_candidate_id': winner['candidate_id'], 'validation_candidates': ranked,
        'test_result': test_result, 'metrics': test_result['metrics'],
        'quality_notes': test_result.get('quality_notes', []) + ['验证期选择参数；测试期不参与排名。多次重复查看测试期仍可能产生研究偏差。'],
    }
