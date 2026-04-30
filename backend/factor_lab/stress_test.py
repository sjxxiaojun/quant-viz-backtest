import csv
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from engine import BacktestEngine, CostModel
from position_manager import PositionManager
from strategy_registry import STRATEGY_REGISTRY


@dataclass(frozen=True)
class ScenarioSpec:
    key: str
    name_cn: str
    annual_drift: float
    annual_vol: float
    market_beta_bias: float = 1.0
    mean_reversion: float = 0.0


SCENARIO_SPECS: Dict[str, ScenarioSpec] = {
    "bull": ScenarioSpec("bull", "牛市年", annual_drift=0.18, annual_vol=0.22, market_beta_bias=1.05),
    "bear": ScenarioSpec("bear", "熊市年", annual_drift=-0.25, annual_vol=0.32, market_beta_bias=1.15),
    "sideways": ScenarioSpec(
        "sideways",
        "震荡年",
        annual_drift=0.02,
        annual_vol=0.16,
        market_beta_bias=0.85,
        mean_reversion=0.08,
    ),
}


@dataclass
class StressTestConfig:
    pool: str = "core"
    max_symbols: int = 30
    top_n: int = 5
    initial_capital: float = 1_000_000.0
    factors: List[str] = field(default_factory=lambda: ["ml_factor_ranker"])
    horizon_days: int = 252
    paths_per_scenario: int = 2
    seed: int = 42
    scenarios: List[str] = field(default_factory=lambda: ["bull", "bear", "sideways"])
    anchor_date: Optional[str] = None
    lookback_days: int = 260
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001
    slippage_rate: float = 0.0003
    stop_loss: float = -0.08


def _json_safe(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _atomic_to_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    try:
        df.to_csv(tmp_name, index=False)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _atomic_write_csv_rows(path: Path, fieldnames: List[str], rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _atomic_write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_json_safe(payload), f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _normalize_base_frame(base_df: pd.DataFrame) -> pd.DataFrame:
    if base_df is None or base_df.empty:
        raise ValueError("压力测评需要至少一段真实历史行情作为模拟起点。")

    df = base_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "stock_code", "close"]).copy()
    df["stock_code"] = df["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(df["stock_code"].astype(str))
    if "stock_name" not in df.columns:
        df["stock_name"] = df["stock_code"]
    df["stock_name"] = df["stock_name"].fillna(df["stock_code"]).astype(str)

    for column in ["open", "high", "low", "close", "volume", "amount", "pct_chg", "turn", "turnover_rate", "amplitude"]:
        if column not in df.columns:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["open"] = df["open"].fillna(df["close"])
    df["high"] = df["high"].fillna(df[["open", "close"]].max(axis=1))
    df["low"] = df["low"].fillna(df[["open", "close"]].min(axis=1))
    df["volume"] = df["volume"].fillna(100_000)
    df["amount"] = df["amount"].fillna(df["volume"] * df["close"])
    df["turnover_rate"] = df["turnover_rate"].fillna(df.get("turn", 1.0)).fillna(1.0)
    df["turn"] = df["turn"].fillna(df["turnover_rate"])
    df["amplitude"] = df["amplitude"].fillna(((df["high"] - df["low"]) / df["close"].replace(0, np.nan)) * 100.0)
    df = df.sort_values(["stock_code", "date"]).drop_duplicates(["stock_code", "date"], keep="last")
    return df


def _prepare_lookback(base_df: pd.DataFrame, config: StressTestConfig) -> Tuple[pd.DataFrame, str]:
    df = _normalize_base_frame(base_df)
    anchor_ts = pd.to_datetime(config.anchor_date) if config.anchor_date else df["date"].max()
    df = df[df["date"] <= anchor_ts].copy()
    if df.empty:
        raise ValueError("压力测评起点之前没有可用真实行情。")
    lookback = (
        df.sort_values(["stock_code", "date"])
        .groupby("stock_code", group_keys=False)
        .tail(config.lookback_days)
        .copy()
    )
    if lookback["stock_code"].nunique() < 3:
        raise ValueError("压力测评至少需要 3 只标的用于构造市场路径。")
    lookback["date"] = lookback["date"].dt.strftime("%Y-%m-%d")
    return lookback, anchor_ts.strftime("%Y-%m-%d")


def _estimate_stock_params(lookback: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    frame = lookback.sort_values(["stock_code", "date"]).copy()
    frame["ret"] = frame.groupby("stock_code")["close"].pct_change()
    market_ret = frame.groupby("date")["ret"].mean().rename("market_ret")
    frame = frame.merge(market_ret, on="date", how="left")

    params: Dict[str, Dict[str, float]] = {}
    market_var = float(frame["market_ret"].var(skipna=True) or 0.0)
    for code, group in frame.groupby("stock_code", sort=False):
        valid = group[["ret", "market_ret"]].dropna()
        beta = 1.0
        residual_vol = 0.015
        if len(valid) >= 20 and market_var > 1e-10:
            beta = float(valid["ret"].cov(valid["market_ret"]) / market_var)
            residual = valid["ret"] - beta * valid["market_ret"]
            residual_vol = float(residual.std() or 0.015)
        params[code] = {
            "beta": float(np.clip(beta, 0.2, 2.5)),
            "residual_vol": float(np.clip(residual_vol, 0.004, 0.045)),
        }
    return params


def _future_dates(anchor_date: str, horizon_days: int) -> List[str]:
    start = pd.to_datetime(anchor_date) + pd.tseries.offsets.BDay(1)
    return [dt.strftime("%Y-%m-%d") for dt in pd.bdate_range(start=start, periods=horizon_days)]


def simulate_future_market_path(
    lookback: pd.DataFrame,
    scenario: ScenarioSpec,
    horizon_days: int,
    rng: np.random.Generator,
    anchor_date: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    stock_params = _estimate_stock_params(lookback)
    future_dates = _future_dates(anchor_date, horizon_days)
    last_rows = lookback.sort_values(["stock_code", "date"]).groupby("stock_code", sort=False).tail(1)
    last_by_code = {row["stock_code"]: row for _, row in last_rows.iterrows()}

    daily_drift = scenario.annual_drift / 252.0
    daily_vol = scenario.annual_vol / np.sqrt(252.0)
    market_state = 0.0
    generated_rows: List[Dict[str, object]] = []

    for date in future_dates:
        market_ret = float(rng.normal(daily_drift, daily_vol))
        if scenario.mean_reversion:
            market_ret -= scenario.mean_reversion * market_state / 252.0
        market_state += market_ret

        for code, last in list(last_by_code.items()):
            params = stock_params.get(code, {"beta": 1.0, "residual_vol": 0.015})
            prev_close = float(last["close"])
            residual = float(rng.normal(0.0, params["residual_vol"]))
            stock_ret = np.clip(scenario.market_beta_bias * params["beta"] * market_ret + residual, -0.095, 0.095)
            open_ret = np.clip(stock_ret * 0.35 + rng.normal(0.0, params["residual_vol"] * 0.35), -0.095, 0.095)
            close = max(0.01, prev_close * (1.0 + stock_ret))
            open_price = max(0.01, prev_close * (1.0 + open_ret))
            range_pct = abs(stock_ret) * 0.65 + float(rng.uniform(0.002, 0.024))
            high = max(open_price, close) * (1.0 + range_pct)
            low = max(0.01, min(open_price, close) * (1.0 - range_pct))
            volume = max(1.0, float(last.get("volume", 100_000)) * float(rng.lognormal(0.0, 0.18)))
            turnover_rate = max(0.01, float(last.get("turnover_rate", last.get("turn", 1.0)) or 1.0) * float(rng.lognormal(0.0, 0.12)))
            amount = volume * close
            row = {
                "date": date,
                "stock_code": code,
                "stock_name": str(last.get("stock_name", code)),
                "open": float(open_price),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
                "amount": float(amount),
                "pct_chg": float(stock_ret * 100.0),
                "turn": float(turnover_rate),
                "turnover_rate": float(turnover_rate),
                "amplitude": float((high - low) / prev_close * 100.0),
                "pe": float(last.get("pe", np.nan)) if pd.notna(last.get("pe", np.nan)) else np.nan,
                "pb": float(last.get("pb", np.nan)) if pd.notna(last.get("pb", np.nan)) else np.nan,
                "ps": float(last.get("ps", np.nan)) if pd.notna(last.get("ps", np.nan)) else np.nan,
                "pcf": float(last.get("pcf", np.nan)) if pd.notna(last.get("pcf", np.nan)) else np.nan,
            }
            generated_rows.append(row)
            last_by_code[code] = pd.Series(row)

    future = pd.DataFrame(generated_rows)
    combined = pd.concat([lookback, future], ignore_index=True, sort=False)
    return combined, future, future_dates


def _benchmark_from_future(future: pd.DataFrame) -> pd.DataFrame:
    market = future.groupby("date", sort=False)["close"].mean().reset_index()
    if market.empty:
        return market
    first = float(market.iloc[0]["close"])
    market["close"] = market["close"] / first * 100.0 if first > 0 else 100.0
    return market[["date", "close"]]


def _downsample_history(history: List[Dict[str, object]], max_points: int = 36) -> List[Dict[str, object]]:
    if len(history) <= max_points:
        selected = history
    else:
        idx = sorted(set(np.linspace(0, len(history) - 1, max_points).astype(int).tolist()))
        selected = [history[i] for i in idx]
    return [
        {
            "date": row.get("date"),
            "total_value": float(row.get("total_value", 0.0) or 0.0),
            "drawdown": float(row.get("drawdown", 0.0) or 0.0),
        }
        for row in selected
    ]


def _run_backtest_on_frame(
    frame: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    factor: str,
    config: StressTestConfig,
    start_date: str,
    end_date: str,
) -> Dict[str, object]:
    strategy_spec = STRATEGY_REGISTRY.get(factor)
    if strategy_spec is None:
        raise ValueError(f"压力测评不支持未知策略: {factor}")

    df = strategy_spec.func(frame.copy())
    resolved_max_hold_days = strategy_spec.default_max_hold_days
    pos_manager = PositionManager(
        max_positions=max(1, config.top_n),
        weight_mode="score",
        max_hold_days=resolved_max_hold_days,
        strategy_spec=strategy_spec,
    )
    engine = None
    signal_by_date = {date: group for date, group in df.groupby("date", sort=False)}
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

    cost_model = CostModel(
        commission_rate=config.commission_rate,
        stamp_tax_rate=config.stamp_tax_rate,
        slippage_rate=config.slippage_rate,
    )
    engine_kwargs = {
        "initial_capital": config.initial_capital,
        "cost_model": cost_model,
        "stock_stop_loss": config.stop_loss,
    }
    try:
        import inspect

        params = inspect.signature(BacktestEngine.__init__).parameters
        if "execution_mode" in params:
            engine_kwargs["execution_mode"] = strategy_spec.execution_mode
    except Exception:
        pass

    engine = BacktestEngine(**engine_kwargs)
    result = engine.run_backtest(df, signal_func, start_date, end_date, benchmark_data=benchmark_df)
    result["strategy_behavior"] = {
        "factor": factor,
        "signal_type": strategy_spec.signal_type,
        "holding_policy": strategy_spec.holding_policy,
        "resolved_max_hold_days": resolved_max_hold_days,
        "execution_mode": strategy_spec.execution_mode,
    }
    return result


def _summarize_factor(metrics: pd.DataFrame) -> Dict[str, float]:
    if metrics.empty:
        return {}
    total_return = metrics["total_return"].astype(float)
    max_drawdown = metrics["max_drawdown"].astype(float)
    final_value = metrics["final_value"].astype(float)
    sharpe = metrics["sharpe_ratio"].astype(float)
    total_trades = metrics["total_trades"].astype(float)
    return {
        "median_total_return": float(total_return.median()),
        "p05_total_return": float(total_return.quantile(0.05)),
        "p95_total_return": float(total_return.quantile(0.95)),
        "prob_positive": float((total_return > 0).mean()),
        "median_max_drawdown": float(max_drawdown.median()),
        "p95_max_drawdown_abs": float(max_drawdown.abs().quantile(0.95)),
        "median_sharpe": float(sharpe.median()),
        "median_final_value": float(final_value.median()),
        "survival_rate": float((max_drawdown > -0.30).mean()),
        "median_total_trades": float(total_trades.median()),
    }


def run_factor_lab_stress_test(
    base_df: pd.DataFrame,
    config: StressTestConfig,
    output_dir: Path,
) -> Dict[str, object]:
    lookback, anchor_date = _prepare_lookback(base_df, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = "stress_%s" % datetime.now().strftime("%Y%m%d_%H%M%S")

    path_metrics: List[Dict[str, object]] = []
    sample_path_rows: List[Dict[str, object]] = []
    sample_paths_by_scenario: Dict[str, List[Dict[str, object]]] = {scenario: [] for scenario in config.scenarios}

    scenario_list = [SCENARIO_SPECS[key] for key in config.scenarios if key in SCENARIO_SPECS]
    for scenario_idx, scenario in enumerate(scenario_list):
        for path_id in range(config.paths_per_scenario):
            rng = np.random.default_rng(config.seed + scenario_idx * 100_000 + path_id)
            combined, future, future_dates = simulate_future_market_path(
                lookback,
                scenario,
                config.horizon_days,
                rng,
                anchor_date,
            )
            benchmark_df = _benchmark_from_future(future)
            start_date = future_dates[0]
            end_date = future_dates[-1]

            for factor in config.factors:
                result = _run_backtest_on_frame(combined, benchmark_df, factor, config, start_date, end_date)
                summary = result.get("summary", {})
                row = {
                    "run_id": run_id,
                    "scenario": scenario.key,
                    "path_id": path_id,
                    "factor": factor,
                    "total_return": float(result.get("total_return", 0.0) or 0.0),
                    "annual_return": float(summary.get("annual_return", 0.0) or 0.0),
                    "max_drawdown": float(summary.get("max_drawdown", 0.0) or 0.0),
                    "sharpe_ratio": float(summary.get("sharpe_ratio", 0.0) or 0.0),
                    "final_value": float(summary.get("final_value", config.initial_capital) or config.initial_capital),
                    "total_trades": int(summary.get("total_trades", 0) or 0),
                    "cost_pct_initial": float(summary.get("cost_stats", {}).get("cost_pct_initial", 0.0) or 0.0),
                }
                path_metrics.append(row)

                if path_id < 2:
                    history = _downsample_history(result.get("history", []))
                    sample_paths_by_scenario[scenario.key].append(
                        {
                            "path_id": path_id,
                            "factor": factor,
                            "history": history,
                        }
                    )
                    for point in history:
                        sample_path_rows.append(
                            {
                                "scenario": scenario.key,
                                "path_id": path_id,
                                "factor": factor,
                                **point,
                            }
                        )

    metrics_df = pd.DataFrame(path_metrics)
    scenarios = []
    for scenario in scenario_list:
        scenario_metrics = metrics_df[metrics_df["scenario"] == scenario.key] if not metrics_df.empty else pd.DataFrame()
        factors = {}
        for factor in config.factors:
            factors[factor] = _summarize_factor(scenario_metrics[scenario_metrics["factor"] == factor])
        scenarios.append(
            {
                "scenario": scenario.key,
                "name_cn": scenario.name_cn,
                "assumptions": {
                    "annual_drift": scenario.annual_drift,
                    "annual_vol": scenario.annual_vol,
                    "market_beta_bias": scenario.market_beta_bias,
                    "mean_reversion": scenario.mean_reversion,
                },
                "factors": factors,
                "sample_paths": sample_paths_by_scenario.get(scenario.key, []),
            }
        )

    path_metrics_csv = output_dir / "path_metrics.csv"
    sample_paths_csv = output_dir / "sample_paths.csv"
    _atomic_to_csv(metrics_df, path_metrics_csv)
    _atomic_write_csv_rows(
        sample_paths_csv,
        ["scenario", "path_id", "factor", "date", "total_value", "drawdown"],
        sample_path_rows,
    )

    result = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            **asdict(config),
            "anchor_date": anchor_date,
            "symbols": int(lookback["stock_code"].nunique()),
        },
        "scenarios": scenarios,
        "artifacts": {
            "summary_json": str(output_dir / "latest_summary.json"),
            "path_metrics_csv": str(path_metrics_csv),
            "sample_paths_csv": str(sample_paths_csv),
        },
        "disclaimer": "情景测评是基于随机路径的压力测试，不是对未来行情或收益的承诺。",
    }
    result = _json_safe(result)
    _atomic_write_json(output_dir / "latest_summary.json", result)
    return result


def load_latest_stress_test(output_dir: Path) -> Optional[Dict[str, object]]:
    path = output_dir / "latest_summary.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
