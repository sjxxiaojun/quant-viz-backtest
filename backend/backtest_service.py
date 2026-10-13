"""Backtest computation independent of HTTP route registration."""
import dataclasses
import inspect
import threading
from dataclasses import dataclass
from typing import Dict, Optional
from fastapi import HTTPException
from api_models import BacktestRequest
from engine import CostModel
from data_manager import DataFetchError, PoolDataFetchError
from research_contracts import DataContractError, ENGINE_VERSION, persist_snapshot
from job_service import report_stage

@dataclass
class BacktestContext:
    strategy_version_store: object
    prepare_universe: object
    data_manager: object
    execution_data_service: object
    semaphore: object
    max_rows: int
    engine_type: object
    position_type: object
    resolve_slippage: object

def execute_backtest(
    req: BacktestRequest,
    override_cost_model: Optional[CostModel] = None,
    allow_mock: bool = False,
    semaphore: Optional[threading.BoundedSemaphore] = None,
    *, context, prepared=None,
) -> Dict:
    strategy_version_store = context.strategy_version_store
    prepare_backtest_universe = context.prepare_universe
    data_manager = context.data_manager
    execution_data_service = context.execution_data_service
    BACKTEST_SEMAPHORE = context.semaphore
    BACKTEST_MAX_ROWS = context.max_rows
    BacktestEngine = context.engine_type
    PositionManager = context.position_type
    resolve_close_slippage_rate = context.resolve_slippage
    if strategy_version_store.resolve_strategy_spec(req.factor) is None:
        raise HTTPException(status_code=422, detail=f"未知策略：{req.factor}")
    if req.weight_mode not in {"equal", "score"}:
        raise HTTPException(status_code=422, detail="weight_mode 仅支持 equal/score")
    report_stage("选择历史股票池")
    current_pool, pool_ctx, warmup_start = prepare_backtest_universe(req) if prepared is None else (prepared["symbols"], prepared["universe"], prepared["warmup_start"])
    # 默认使用普通回测并发预算；Factor Lab 等内部编排传入自己的信号量，与用户回测互不抢占。
    slot = semaphore if semaphore is not None else BACKTEST_SEMAPHORE
    if not slot.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="当前已有回测任务运行中，请稍后再试。")

    try:
        if prepared is None:
            df, data_sources = data_manager.get_stock_pool_data(
                current_pool, warmup_start, req.end_date, allow_mock=allow_mock,
                allow_late_start=bool(pool_ctx.get("allow_late_start")),
            )
        else:
            df, data_sources = prepared["frame"].copy(), prepared["sources"]
    except (DataFetchError, PoolDataFetchError) as exc:
        slot.release()
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception:
        slot.release()
        raise

    try:
        if df.empty:
            raise HTTPException(status_code=400, detail="未获取到行情数据。")
        if len(df) > BACKTEST_MAX_ROWS:
            raise HTTPException(
                status_code=413,
                detail=f"实际加载 {len(df):,} 行行情，超过单次预算 {BACKTEST_MAX_ROWS:,} 行。",
            )

        benchmark_df = None
        benchmark_warning = None
        try:
            benchmark_df, _ = (prepared.get("benchmark"), "FROZEN") if prepared is not None else data_manager.get_stock_data(
                "510300",
                req.start_date,
                req.end_date,
                allow_mock=allow_mock,
            )
        except DataFetchError as exc:
            # Do not block strategy backtest if benchmark data is temporarily unavailable.
            benchmark_warning = str(exc)

        report_stage("校验未复权成交数据")
        try:
            df = execution_data_service.prepare(df, allow_approximate=req.price_mode == "approximate_adjusted" or allow_mock) if prepared is None else df
        except DataContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        from research_contracts import snapshot_fingerprint
        from research_metrics import code_fingerprint, runtime_versions
        snapshot_id = prepared["snapshot_id"] if prepared is not None else persist_snapshot(df, req.model_dump(), {**pool_ctx, "symbols": current_pool, "benchmark_fingerprint": snapshot_fingerprint(benchmark_df, {}), "replay_code": code_fingerprint(), "replay_runtime": runtime_versions()})
        from research_metrics import save_replay_context
        if prepared is None:
            save_replay_context(snapshot_id, current_pool, pool_ctx, warmup_start, data_sources, benchmark_df)
        report_stage("生成信号与逐日撮合")
        strategy_spec = prepared.get('strategy_spec') if prepared is not None else None
        strategy_spec = strategy_spec or strategy_version_store.resolve_strategy_spec(req.factor)
        from research_metrics import strategy_identity
        identity = prepared.get('strategy_identity') if prepared is not None else None
        identity = identity or strategy_identity(strategy_version_store, req.factor, strategy_spec)
        if strategy_spec is not None:
            strategy_func = strategy_spec.func
            df = strategy_func(df)
        else:
            def _calc_mom(g):
                g = g.copy()
                g["mom"] = g["close"].pct_change(20)
                g["signal"] = 0
                g.loc[g["mom"] > 0.1, "signal"] = 1
                g.loc[g["mom"] < 0, "signal"] = -1
                return g

            df = df.groupby("stock_code", group_keys=False).apply(_calc_mom)

        resolved_max_hold_days = req.max_hold_days
        resolved_take_profit = req.take_profit
        if strategy_spec is not None:
            if resolved_max_hold_days is None:
                resolved_max_hold_days = strategy_spec.default_max_hold_days
            if resolved_take_profit is None:
                resolved_take_profit = strategy_spec.default_take_profit

        pos_manager = PositionManager(
            max_positions=req.max_positions,
            weight_mode=req.weight_mode,
            max_hold_days=resolved_max_hold_days,
            strategy_spec=strategy_spec,
        )

        engine = None

        signal_by_date = {
            date: group
            for date, group in df.groupby("date", sort=False)
        }
        empty_signals = df.iloc[0:0]

        def signal_func(date, day_data):
            day_signals = signal_by_date.get(date, empty_signals)
            if day_signals.empty:
                return {}
            current_positions = engine.portfolio.positions if engine is not None else None
            return pos_manager.generate_target_weights(
                date,
                day_data,
                day_signals,
                current_positions=current_positions,
            )

        cost_model = override_cost_model or CostModel(
            commission_rate=req.commission_rate,
            commission_min=0.0 if req.commission_rate == 0 else req.commission_min,
            stamp_tax_rate=req.stamp_tax_rate,
            slippage_rate=req.slippage_rate,
            close_slippage_rate=resolve_close_slippage_rate(req),
        )
        engine_kwargs = {
            "initial_capital": req.initial_capital,
            "cost_model": cost_model,
            "stock_stop_loss": req.stop_loss,
        }
        engine_params = inspect.signature(BacktestEngine.__init__).parameters
        if strategy_spec is not None and "execution_mode" in engine_params:
            engine_kwargs["execution_mode"] = strategy_spec.execution_mode if req.same_close_approximation else "next_open_rebalance"
        if resolved_take_profit is not None:
            if "stock_take_profit" in engine_params:
                engine_kwargs["stock_take_profit"] = resolved_take_profit
            elif "take_profit" in engine_params:
                engine_kwargs["take_profit"] = resolved_take_profit

        engine = BacktestEngine(**engine_kwargs)
        result = engine.run_backtest(df, signal_func, req.start_date, req.end_date, benchmark_data=benchmark_df)
        result.update({"engine_version": ENGINE_VERSION, "data_snapshot_id": snapshot_id,
                       "signal_as_of": str(df.date.max()), "request": req.model_dump(),
                       "data_as_of": str(df.date.max()), "strategy_version": strategy_version_store.get_active_version_id(req.factor),
                       "quality_notes": ["固定样本不保证无幸存者偏差", "分红按记录的现金金额计提；未包含差别化股息税", "日线成交量容量为近似，非开盘盘口容量", "触及涨跌停视为不可成交；无法重建封单和开板过程", "同日止盈止损按引擎声明的保守顺序处理"]})
        if req.price_mode == "approximate_adjusted" or allow_mock or req.same_close_approximation:
            result["quality_notes"].append("近似研究结果，不可作为新版模拟账户成交依据")
        result["data_sources_used"] = data_sources
        result["data_quality"] = data_manager._build_pool_quality(df, current_pool, warmup_start, req.end_date, data_sources, allow_late_start=bool(pool_ctx.get("allow_late_start")))
        result["resolved_pool"] = {
            "requested_pool": req.pool,
            **pool_ctx,
        }
        result["strategy_behavior"] = {
            "factor": req.factor,
            "signal_type": strategy_spec.signal_type if strategy_spec is not None else "custom",
            "holding_policy": strategy_spec.holding_policy if strategy_spec is not None else "custom",
            "resolved_max_hold_days": resolved_max_hold_days,
            "resolved_take_profit": resolved_take_profit,
            "execution_mode": engine.execution_mode,
            "portfolio_circuit_breaker_active": False,
            "deprecated_circuit_breaker_requested": req.circuit_breaker,
            "risk_control_note": "组合熔断已停用；组合回撤仅作为风险指标展示。",
            # 本次实际生效的成本口径（含零成本对照组），让"我设的滑点到底有没有生效"
            # 可以直接从回测结果里核对，而不是靠猜。字段随 CostModel 自动同步。
            "effective_cost_model": dataclasses.asdict(cost_model),
        }
        if benchmark_warning:
            result.setdefault("warnings", []).append(
                {
                    "code": "BENCHMARK_UNAVAILABLE",
                    "message": benchmark_warning,
                }
            )
        from research_metrics import enrich_result
        enrich_result(result, req, snapshot_id)
        result['provenance']['strategy'] = identity
        result["trades_total"] = len(result.get("trades", []))
        result["trades_truncated"] = False
        return result
    finally:
        slot.release()

