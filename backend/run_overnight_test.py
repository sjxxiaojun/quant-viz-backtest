import inspect
import os
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

from engine import BacktestEngine, CostModel
from position_manager import PositionManager
from strategy_registry import STRATEGY_REGISTRY
from strategies.signal_factory import _prepare_overnight_features, calculate_overnight_hold_signals


DATA_DIR = "data_cache/decade_study"
BENCHMARK_PATH = "/Users/gdxj/quant_data_lake/etf/510300_full_history.parquet"
OUTPUT_DIR = "../results/quant-factor-mining/reports/overnight_study"
WINDOWS = [
    ("近一年", "2025-04-21", "2026-04-20"),
    ("全样本", "2016-01-01", "2026-04-20"),
]
EXPERIMENTS = [
    {
        "variant": "baseline_old",
        "label": "基线: 旧执行语义",
        "strategy_key": "overnight",
        "execution_mode": "next_open_rebalance",
        "max_positions": 2,
        "weight_mode": "equal",
        "family": "baseline",
    },
    {
        "variant": "current_aligned",
        "label": "修正执行语义版",
        "strategy_key": "overnight",
        "execution_mode": STRATEGY_REGISTRY["overnight"].execution_mode,
        "max_positions": 2,
        "weight_mode": "equal",
        "family": "current",
    },
    {
        "variant": "candidate_a_quality",
        "label": "方案A 质量收缩版",
        "strategy_key": "overnight_quality",
        "execution_mode": STRATEGY_REGISTRY["overnight_quality"].execution_mode,
        "max_positions": 2,
        "weight_mode": "score",
        "family": "candidate",
    },
    {
        "variant": "candidate_b_balanced",
        "label": "方案B 平衡推荐版",
        "strategy_key": "overnight_balanced",
        "execution_mode": STRATEGY_REGISTRY["overnight_balanced"].execution_mode,
        "max_positions": 2,
        "weight_mode": "score",
        "family": "candidate",
    },
    {
        "variant": "candidate_c_ranked",
        "label": "方案C 打分排序版",
        "strategy_key": "overnight_ranked",
        "execution_mode": STRATEGY_REGISTRY["overnight_ranked"].execution_mode,
        "max_positions": 1,
        "weight_mode": "score",
        "family": "candidate",
    },
]


def load_decade_data() -> pd.DataFrame:
    frames = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith(".parquet"):
            frames.append(pd.read_parquet(os.path.join(DATA_DIR, filename)))
    return pd.concat(frames).sort_values(["date", "stock_code"]).reset_index(drop=True)


def load_benchmark_data() -> pd.DataFrame:
    if not os.path.exists(BENCHMARK_PATH):
        return pd.DataFrame()
    benchmark = pd.read_parquet(BENCHMARK_PATH)
    return benchmark[["date", "close"]].sort_values("date").reset_index(drop=True)


def build_cost_profiles() -> Dict[str, CostModel]:
    return {
        "zero_cost": CostModel(
            commission_rate=0.0,
            commission_min=0.0,
            stamp_tax_rate=0.0,
            slippage_rate=0.0,
            use_order_slicing=False,
        ),
        "current_cost": CostModel(
            commission_rate=0.0003,
            slippage_rate=0.001,
        ),
    }


def build_engine_kwargs(strategy_spec, execution_mode: str, cost_model: CostModel) -> Dict:
    engine_kwargs = {
        "initial_capital": 1000000,
        "cost_model": cost_model,
        "execution_mode": execution_mode,
    }
    engine_params = inspect.signature(BacktestEngine.__init__).parameters
    if strategy_spec.default_take_profit is not None:
        if "stock_take_profit" in engine_params:
            engine_kwargs["stock_take_profit"] = strategy_spec.default_take_profit
        elif "take_profit" in engine_params:
            engine_kwargs["take_profit"] = strategy_spec.default_take_profit
    return engine_kwargs


def aggregate_signal_stats(decision_log: List[Dict]) -> Dict[str, float]:
    if not decision_log:
        return {
            "signal_days": 0,
            "raw_signal_count": 0,
            "selected_signal_count": 0,
            "selection_rate": 0.0,
            "dropped_by_max_positions": 0,
            "capacity_capped_days": 0,
            "ranking_basis": "none",
        }

    raw_signal_count = sum(int(item.get("raw_signal_count", 0)) for item in decision_log)
    selected_signal_count = sum(int(item.get("selected_signal_count", 0)) for item in decision_log)
    ranking_modes = [str(item.get("ranking_basis", "stock_code")) for item in decision_log]
    ranking_basis = max(set(ranking_modes), key=ranking_modes.count)
    return {
        "signal_days": len(decision_log),
        "raw_signal_count": raw_signal_count,
        "selected_signal_count": selected_signal_count,
        "selection_rate": float(selected_signal_count / raw_signal_count) if raw_signal_count > 0 else 0.0,
        "dropped_by_max_positions": sum(int(item.get("dropped_by_max_positions", 0)) for item in decision_log),
        "capacity_capped_days": sum(1 for item in decision_log if item.get("capacity_capped")),
        "ranking_basis": ranking_basis,
    }


def run_window_backtest(
    strategy_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    experiment: Dict,
    cost_profile: str,
    cost_model: CostModel,
    start_date: str,
    end_date: str,
) -> Tuple[Dict, Dict]:
    strategy_spec = STRATEGY_REGISTRY[experiment["strategy_key"]]
    pos_manager = PositionManager(
        max_positions=experiment["max_positions"],
        weight_mode=experiment["weight_mode"],
        max_hold_days=strategy_spec.default_max_hold_days,
        strategy_spec=strategy_spec,
    )
    decision_log: List[Dict] = []

    def signal_func(date, day_data, current_positions=None):
        day_signals = strategy_df[strategy_df["date"] == date]
        if day_signals.empty:
            return {}
        target_weights = pos_manager.generate_target_weights(
            date,
            day_data,
            day_signals,
            current_positions=current_positions,
        )
        decision_log.append(pos_manager.last_decision_info.copy())
        return target_weights

    engine = BacktestEngine(**build_engine_kwargs(strategy_spec, experiment["execution_mode"], cost_model))
    benchmark_window = benchmark_df[benchmark_df["date"].between(start_date, end_date)].copy()
    result = engine.run_backtest(
        strategy_df,
        signal_func,
        start_date,
        end_date,
        benchmark_data=benchmark_window,
    )
    return result, aggregate_signal_stats(decision_log)


def flatten_metrics(
    experiment: Dict,
    cost_profile: str,
    window_label: str,
    start_date: str,
    end_date: str,
    result: Dict,
    signal_stats: Dict,
) -> Dict:
    summary = result["summary"]
    trade_stats = summary["trade_stats"]
    cost_stats = summary["cost_stats"]
    execution_stats = summary["execution_stats"]
    exposure_stats = summary["exposure_stats"]
    return {
        "variant": experiment["variant"],
        "label": experiment["label"],
        "family": experiment["family"],
        "strategy_key": experiment["strategy_key"],
        "execution_mode": experiment["execution_mode"],
        "cost_profile": cost_profile,
        "window_label": window_label,
        "start_date": start_date,
        "end_date": end_date,
        "total_return": result["total_return"],
        "annual_return": summary["annual_return"],
        "benchmark_return": summary["benchmark_return"],
        "excess_return": summary["excess_return"],
        "max_drawdown": summary["max_drawdown"],
        "sharpe_ratio": summary["sharpe_ratio"],
        "calmar_ratio": summary["calmar_ratio"],
        "win_rate": summary["win_rate"],
        "profit_loss_ratio": summary["profit_loss_ratio"],
        "trade_count": summary["total_trades"],
        "avg_trade_return_net": trade_stats["avg_trade_return_net"],
        "median_trade_return_net": trade_stats["median_trade_return_net"],
        "expectancy_net": trade_stats["expectancy_net"],
        "avg_win_net": trade_stats["avg_win_net"],
        "avg_loss_net": trade_stats["avg_loss_net"],
        "profit_factor_net": trade_stats["profit_factor_net"],
        "avg_holding_days_actual": trade_stats["avg_holding_days_actual"],
        "round_trip_count": trade_stats["round_trip_count"],
        "total_cost": cost_stats["total_cost"],
        "commission_total": cost_stats["commission_total"],
        "stamp_tax_total": cost_stats["stamp_tax_total"],
        "slippage_total": cost_stats["slippage_total"],
        "turnover_amount": cost_stats["turnover_amount"],
        "turnover_ratio": cost_stats["turnover_ratio"],
        "cost_pct_initial": cost_stats["cost_pct_initial"],
        "cost_bps_turnover": cost_stats["cost_bps_turnover"],
        "avg_cost_per_round_trip": cost_stats["avg_cost_per_round_trip"],
        "buy_attempts": execution_stats["buy_attempts"],
        "buy_fills": execution_stats["buy_fills"],
        "buy_fill_rate": execution_stats["buy_fill_rate"],
        "sell_attempts": execution_stats["sell_attempts"],
        "sell_fills": execution_stats["sell_fills"],
        "sell_fill_rate": execution_stats["sell_fill_rate"],
        "blocked_limit_up_buy_count": execution_stats["blocked_limit_up_buy_count"],
        "blocked_limit_down_sell_count": execution_stats["blocked_limit_down_sell_count"],
        "blocked_reentry_after_stop_count": execution_stats["blocked_reentry_after_stop_count"],
        "delayed_exit_count": execution_stats["delayed_exit_count"],
        "invested_days": exposure_stats["invested_days"],
        "invested_ratio": exposure_stats["invested_ratio"],
        "avg_positions": exposure_stats["avg_positions"],
        "avg_cash_ratio": exposure_stats["avg_cash_ratio"],
        "signal_days": signal_stats["signal_days"],
        "raw_signal_count": signal_stats["raw_signal_count"],
        "selected_signal_count": signal_stats["selected_signal_count"],
        "selection_rate": signal_stats["selection_rate"],
        "dropped_by_max_positions": signal_stats["dropped_by_max_positions"],
        "capacity_capped_days": signal_stats["capacity_capped_days"],
        "ranking_basis": signal_stats["ranking_basis"],
    }


def add_cost_drag_metrics(metrics_df: pd.DataFrame) -> pd.DataFrame:
    zero = metrics_df[metrics_df["cost_profile"] == "zero_cost"][
        ["variant", "window_label", "total_return", "avg_trade_return_net"]
    ].rename(
        columns={
            "total_return": "zero_cost_total_return",
            "avg_trade_return_net": "zero_cost_avg_trade_return_net",
        }
    )
    current = metrics_df.merge(zero, on=["variant", "window_label"], how="left")
    current["cost_drag_return"] = current["zero_cost_total_return"] - current["total_return"]
    current["cost_drag_trade"] = current["zero_cost_avg_trade_return_net"] - current["avg_trade_return_net"]
    current["cost_swallow_ratio"] = current.apply(
        lambda row: (
            row["cost_drag_return"] / row["zero_cost_total_return"]
            if row["cost_profile"] == "current_cost" and row["zero_cost_total_return"] > 0
            else None
        ),
        axis=1,
    )
    return current


def compute_annual_metrics(
    strategy_frames: Dict[str, pd.DataFrame],
    benchmark_df: pd.DataFrame,
    cost_model: CostModel,
) -> pd.DataFrame:
    rows = []
    for experiment in EXPERIMENTS:
        for year in range(2016, 2027):
            start_date = f"{year}-01-01"
            end_date = f"{year}-12-31"
            result, signal_stats = run_window_backtest(
                strategy_frames[experiment["strategy_key"]],
                benchmark_df,
                experiment,
                "current_cost",
                cost_model,
                start_date,
                end_date,
            )
            if not result:
                continue
            row = flatten_metrics(
                experiment,
                "current_cost",
                str(year),
                start_date,
                end_date,
                result,
                signal_stats,
            )
            rows.append(row)
    return pd.DataFrame(rows)


def compute_rolling_metrics(history_df: pd.DataFrame, variant: str, label: str) -> pd.DataFrame:
    history_df = history_df.copy().sort_values("date")
    history_df["roll_return_252d"] = history_df["total_value"] / history_df["total_value"].shift(252) - 1
    history_df["roll_sharpe_252d"] = history_df["returns"].rolling(252).mean() / (
        history_df["returns"].rolling(252).std() + 1e-9
    ) * (252 ** 0.5)
    roll_max = history_df["total_value"].rolling(252).max()
    history_df["roll_max_dd_252d"] = (history_df["total_value"] - roll_max) / (roll_max + 1e-9)
    rolling = history_df.dropna(subset=["roll_return_252d"]).copy()
    if rolling.empty:
        return pd.DataFrame()
    return rolling[["date", "roll_return_252d", "roll_sharpe_252d", "roll_max_dd_252d"]].assign(
        variant=variant,
        label=label,
    )


def format_pct(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value * 100:.2f}%"


def format_bp(value) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value * 10000:.1f}"


def format_num(value, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value:.{digits}f}"


def frame_to_markdown(df: pd.DataFrame) -> str:
    render = df.copy()
    headers = list(render.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in render.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in headers) + " |")
    return "\n".join(lines)


def analyze_factors(full_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    features = _prepare_overnight_features(full_df)
    features["next_open"] = features.groupby("stock_code")["open"].shift(-1)
    features["overnight_ret"] = features["next_open"] / features["close"] - 1
    trend_sample = features[
        (features["close"] > features["ma5"])
        & (features["ma5"] > features["ma10"])
        & features["next_open"].notna()
    ].copy()

    current = calculate_overnight_hold_signals(full_df.copy())
    current["next_open"] = current.groupby("stock_code")["open"].shift(-1)
    current["overnight_ret"] = current["next_open"] / current["close"] - 1
    current_signal_sample = current[(current["signal"] == 1) & current["next_open"].notna()].copy()

    diagnostics = {
        "trend_baseline": pd.DataFrame(
            [
                {
                    "window": "近一年",
                    "sample_count": len(trend_sample[trend_sample["date"] >= "2025-04-21"]),
                    "mean_overnight_bp": format_bp(
                        trend_sample[trend_sample["date"] >= "2025-04-21"]["overnight_ret"].mean()
                    ),
                },
                {
                    "window": "全样本",
                    "sample_count": len(trend_sample),
                    "mean_overnight_bp": format_bp(trend_sample["overnight_ret"].mean()),
                },
            ]
        ),
        "current_signal": pd.DataFrame(
            [
                {
                    "window": "近一年",
                    "signal_count": len(current_signal_sample[current_signal_sample["date"] >= "2025-04-21"]),
                    "mean_overnight_bp": format_bp(
                        current_signal_sample[current_signal_sample["date"] >= "2025-04-21"]["overnight_ret"].mean()
                    ),
                },
                {
                    "window": "全样本",
                    "signal_count": len(current_signal_sample),
                    "mean_overnight_bp": format_bp(current_signal_sample["overnight_ret"].mean()),
                },
            ]
        ),
    }

    bucket_specs = {
        "close_strength": [0.0, 0.50, 0.70, 0.80, 0.90, 0.95, 1.01],
        "pct_chg_real": [-1.0, 0.0, 0.01, 0.03, 0.05, 0.07, 0.095, 1.0],
        "vol_ratio": [0.0, 0.8, 1.0, 1.2, 1.5, 2.0, 99.0],
    }
    for column, bins in bucket_specs.items():
        rows = []
        for window_label, start_date, _ in WINDOWS:
            sample = trend_sample[trend_sample["date"] >= start_date].copy()
            grouped = sample.groupby(pd.cut(sample[column], bins=bins, include_lowest=True), observed=False).agg(
                sample_count=("overnight_ret", "size"),
                mean_overnight_bp=("overnight_ret", lambda s: round(float(s.mean() * 10000), 1)),
            )
            grouped = grouped.reset_index().rename(columns={column: "bucket"})
            grouped["window"] = window_label
            rows.append(grouped)
        diagnostics[column] = pd.concat(rows, ignore_index=True)

    joint_rows = []
    joint_rules = [
        ("激进版", 0.95, 0.03, 0.095, 1.3, 2.5),
        ("均衡版", 0.95, 0.02, 0.095, 1.3, 2.5),
        ("量比收紧版", 0.95, 0.03, 0.095, 1.2, 1.8),
        ("样本更宽版", 0.85, 0.03, 0.08, 1.3, 1.8),
    ]
    for name, close_min, pct_min, pct_max, vol_min, vol_max in joint_rules:
        for window_label, start_date, _ in WINDOWS:
            sample = trend_sample[trend_sample["date"] >= start_date].copy()
            rest_mean = sample["overnight_ret"].mean()
            selected = sample[
                (sample["close_strength"] >= close_min)
                & sample["pct_chg_real"].between(pct_min, pct_max)
                & sample["vol_ratio"].between(vol_min, vol_max)
            ].copy()
            joint_rows.append(
                {
                    "rule": name,
                    "window": window_label,
                    "sample_count": len(selected),
                    "mean_overnight_bp": format_bp(selected["overnight_ret"].mean()),
                    "alpha_vs_trend_bp": format_bp(selected["overnight_ret"].mean() - rest_mean),
                }
            )
    diagnostics["joint_rules"] = pd.DataFrame(joint_rows)
    return diagnostics


def build_report(
    metrics_df: pd.DataFrame,
    annual_df: pd.DataFrame,
    rolling_df: pd.DataFrame,
    factor_tables: Dict[str, pd.DataFrame],
) -> str:
    current_cost = metrics_df[metrics_df["cost_profile"] == "current_cost"].copy()
    current_cost = current_cost.sort_values(["window_label", "label"])
    comparison_table = current_cost[
        [
            "label",
            "window_label",
            "total_return",
            "annual_return",
            "excess_return",
            "sharpe_ratio",
            "calmar_ratio",
            "max_drawdown",
            "win_rate",
            "profit_loss_ratio",
            "avg_trade_return_net",
            "trade_count",
            "avg_holding_days_actual",
            "invested_ratio",
        ]
    ].copy()
    for column in ["total_return", "annual_return", "excess_return", "max_drawdown", "win_rate", "avg_trade_return_net", "invested_ratio"]:
        comparison_table[column] = comparison_table[column].map(format_pct)
    comparison_table["sharpe_ratio"] = comparison_table["sharpe_ratio"].map(format_num)
    comparison_table["calmar_ratio"] = comparison_table["calmar_ratio"].map(format_num)
    comparison_table["profit_loss_ratio"] = comparison_table["profit_loss_ratio"].map(format_num)
    comparison_table["avg_holding_days_actual"] = comparison_table["avg_holding_days_actual"].map(format_num)

    cost_table = metrics_df[metrics_df["cost_profile"] == "current_cost"][
        [
            "label",
            "window_label",
            "total_cost",
            "commission_total",
            "stamp_tax_total",
            "slippage_total",
            "cost_bps_turnover",
            "avg_cost_per_round_trip",
            "cost_drag_return",
            "cost_swallow_ratio",
        ]
    ].copy()
    for column in ["total_cost", "commission_total", "stamp_tax_total", "slippage_total", "avg_cost_per_round_trip"]:
        cost_table[column] = cost_table[column].map(lambda value: format_num(value, 2))
    cost_table["cost_bps_turnover"] = cost_table["cost_bps_turnover"].map(lambda value: format_num(value, 1))
    cost_table["cost_drag_return"] = cost_table["cost_drag_return"].map(format_pct)
    cost_table["cost_swallow_ratio"] = cost_table["cost_swallow_ratio"].map(format_pct)

    execution_table = current_cost[
        [
            "label",
            "window_label",
            "buy_attempts",
            "buy_fill_rate",
            "sell_attempts",
            "sell_fill_rate",
            "blocked_limit_up_buy_count",
            "blocked_limit_down_sell_count",
            "delayed_exit_count",
        ]
    ].copy()
    execution_table["buy_fill_rate"] = execution_table["buy_fill_rate"].map(format_pct)
    execution_table["sell_fill_rate"] = execution_table["sell_fill_rate"].map(format_pct)

    signal_table = current_cost[
        [
            "label",
            "window_label",
            "signal_days",
            "raw_signal_count",
            "selected_signal_count",
            "selection_rate",
            "dropped_by_max_positions",
            "capacity_capped_days",
            "ranking_basis",
        ]
    ].copy()
    signal_table["selection_rate"] = signal_table["selection_rate"].map(format_pct)

    annual_summary = annual_df[
        ["label", "window_label", "total_return", "max_drawdown", "trade_count", "avg_trade_return_net", "cost_bps_turnover"]
    ].copy()
    annual_summary["total_return"] = annual_summary["total_return"].map(format_pct)
    annual_summary["max_drawdown"] = annual_summary["max_drawdown"].map(format_pct)
    annual_summary["avg_trade_return_net"] = annual_summary["avg_trade_return_net"].map(format_pct)
    annual_summary["cost_bps_turnover"] = annual_summary["cost_bps_turnover"].map(lambda value: format_num(value, 1))

    rolling_recent = rolling_df.sort_values("date").groupby("label").tail(5).copy()
    rolling_recent["roll_return_252d"] = rolling_recent["roll_return_252d"].map(format_pct)
    rolling_recent["roll_sharpe_252d"] = rolling_recent["roll_sharpe_252d"].map(format_num)
    rolling_recent["roll_max_dd_252d"] = rolling_recent["roll_max_dd_252d"].map(format_pct)

    lines = [
        "# Overnight Strategy Research",
        "",
        "## 1. 因子诊断",
        "",
        "### 趋势样本基线",
        frame_to_markdown(factor_tables["trend_baseline"]),
        "",
        "### 当前规则信号样本",
        frame_to_markdown(factor_tables["current_signal"]),
        "",
        "### close_strength 分桶",
        frame_to_markdown(factor_tables["close_strength"]),
        "",
        "### pct_chg_real 分桶",
        frame_to_markdown(factor_tables["pct_chg_real"]),
        "",
        "### vol_ratio 分桶",
        frame_to_markdown(factor_tables["vol_ratio"]),
        "",
        "### 联合过滤区间",
        frame_to_markdown(factor_tables["joint_rules"]),
        "",
        "## 2. 主回测对比",
        "",
        frame_to_markdown(comparison_table),
        "",
        "## 3. 成本拆解",
        "",
        frame_to_markdown(cost_table),
        "",
        "## 4. 执行与可成交性",
        "",
        frame_to_markdown(execution_table),
        "",
        "## 5. 信号漏斗",
        "",
        frame_to_markdown(signal_table),
        "",
        "## 6. 年度表现（current_cost）",
        "",
        frame_to_markdown(annual_summary),
        "",
        "## 7. 近 5 个滚动窗口摘要（252 交易日）",
        "",
        frame_to_markdown(rolling_recent[["label", "date", "roll_return_252d", "roll_sharpe_252d", "roll_max_dd_252d"]]),
        "",
        "## 8. 推荐",
        "",
        "- 当前结论：在现有成本模型下，所有方案的全样本净收益仍为负，还不能直接视为可实盘版本。",
        "- 下一轮主研究候选：方案B 平衡推荐版。它在全样本成本后回撤最浅、亏损最小，同时保留了较好的零成本 alpha 与较低交易频率。",
        "- 近一年成本后更占优的是方案A / 方案C：A 更收缩，C 更偏 top1 排序；如果下一轮更关注最近行情适应性，可以继续围绕这两条线做微调。",
        "- 继续优化的重点应放在成交成本与容量控制，而不是再单纯追更激进的毛 alpha。",
        "",
    ]
    return "\n".join(lines)


def run_overnight_research():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    full_df = load_decade_data()
    benchmark_df = load_benchmark_data()
    cost_profiles = build_cost_profiles()
    strategy_frames = {
        strategy_key: STRATEGY_REGISTRY[strategy_key].func(full_df.copy())
        for strategy_key in sorted({experiment["strategy_key"] for experiment in EXPERIMENTS})
    }

    metrics_rows = []
    full_results: Dict[Tuple[str, str], Dict] = {}
    for experiment in EXPERIMENTS:
        for window_label, start_date, end_date in WINDOWS:
            for cost_name, cost_model in cost_profiles.items():
                print(
                    f"Running {experiment['label']} | {cost_name} | {window_label} "
                    f"{start_date} -> {end_date}"
                )
                result, signal_stats = run_window_backtest(
                    strategy_frames[experiment["strategy_key"]],
                    benchmark_df,
                    experiment,
                    cost_name,
                    cost_model,
                    start_date,
                    end_date,
                )
                metrics_rows.append(
                    flatten_metrics(
                        experiment,
                        cost_name,
                        window_label,
                        start_date,
                        end_date,
                        result,
                        signal_stats,
                    )
                )
                if window_label == "全样本" and cost_name == "current_cost":
                    full_results[(experiment["variant"], cost_name)] = result

    metrics_df = add_cost_drag_metrics(pd.DataFrame(metrics_rows))
    annual_df = compute_annual_metrics(strategy_frames, benchmark_df, cost_profiles["current_cost"])
    annual_df = annual_df.rename(columns={"window_label": "year"})
    annual_df["window_label"] = annual_df["start_date"].str.slice(0, 4)

    rolling_rows = []
    for experiment in EXPERIMENTS:
        result = full_results[(experiment["variant"], "current_cost")]
        history_df = pd.DataFrame(result["history"])
        if history_df.empty:
            continue
        rolling_rows.append(compute_rolling_metrics(history_df, experiment["variant"], experiment["label"]))
    rolling_df = pd.concat(rolling_rows, ignore_index=True) if rolling_rows else pd.DataFrame()

    factor_tables = analyze_factors(full_df)
    report = build_report(metrics_df, annual_df, rolling_df, factor_tables)

    output_dir = Path(OUTPUT_DIR)
    report_path = output_dir / "overnight_strategy_research.md"
    comparison_csv = output_dir / "overnight_comparison_metrics.csv"
    annual_csv = output_dir / "overnight_annual_metrics.csv"
    rolling_csv = output_dir / "overnight_rolling_metrics.csv"

    report_path.write_text(report, encoding="utf-8")
    metrics_df.to_csv(comparison_csv, index=False)
    annual_df.to_csv(annual_csv, index=False)
    if not rolling_df.empty:
        rolling_df.to_csv(rolling_csv, index=False)

    print(f"Research report written to {report_path}")
    print(f"Comparison metrics written to {comparison_csv}")
    print(f"Annual metrics written to {annual_csv}")
    if not rolling_df.empty:
        print(f"Rolling metrics written to {rolling_csv}")


if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    run_overnight_research()
