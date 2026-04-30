from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

import pandas as pd

from strategy_registry import StrategySpec


@dataclass
class HoldingInfo:
    code: str
    entry_date: str
    entry_price: float
    holding_bars: int = 0
    last_seen_date: Optional[str] = None


class BaseHoldingPolicy:
    def __init__(
        self,
        max_positions: int,
        weight_mode: str,
        max_hold_days: Optional[int] = None,
    ):
        self.max_positions = max_positions
        self.weight_mode = weight_mode
        self.max_hold_days = max_hold_days
        self.holdings: Dict[str, HoldingInfo] = {}

    def _days_between(self, d1_str: str, d2_str: str) -> int:
        d1 = datetime.strptime(d1_str, "%Y-%m-%d")
        d2 = datetime.strptime(d2_str, "%Y-%m-%d")
        return len(pd.bdate_range(d1, d2)) - 1

    def _is_expired(self, holding: HoldingInfo, date: str) -> bool:
        if self.max_hold_days is None:
            return False
        return holding.holding_bars >= self.max_hold_days

    def _advance_holding_bars(self, date: str) -> None:
        for holding in self.holdings.values():
            if holding.last_seen_date == date:
                continue
            if holding.last_seen_date is None:
                holding.holding_bars = max(holding.holding_bars, self._days_between(holding.entry_date, date))
            else:
                holding.holding_bars += 1
            holding.last_seen_date = date

    def _sync_actual_positions(self, current_positions: Optional[Dict]):
        if current_positions is None:
            return

        actual_codes = set(current_positions.keys())
        for code in list(self.holdings.keys()):
            if code not in actual_codes:
                del self.holdings[code]

        for code, position in current_positions.items():
            if code in self.holdings:
                continue
            entry_date = self._position_value(position, ["entry_date"], "1900-01-01")
            entry_price = self._position_value(
                position,
                ["entry_price", "avg_price", "cost_price", "current_price"],
                0.0,
            )
            self.holdings[code] = HoldingInfo(
                code=code,
                entry_date=str(entry_date),
                entry_price=float(entry_price or 0.0),
                holding_bars=0,
            )

    @staticmethod
    def _position_value(position, names, default=None):
        for name in names:
            if isinstance(position, dict) and position.get(name) is not None:
                return position.get(name)
            if hasattr(position, name):
                value = getattr(position, name)
                if value is not None:
                    return value
        return default

    def _rank_candidates(self, df: pd.DataFrame) -> pd.DataFrame:
        ranked = df.copy()
        if ranked.empty:
            return ranked
        sort_cols = ["stock_code"]
        ascending = [True]
        if "score" in ranked.columns:
            sort_cols = ["score", "stock_code"]
            ascending = [False, True]
        ranked = ranked.sort_values(sort_cols, ascending=ascending)
        return ranked.drop_duplicates(subset=["stock_code"], keep="first")

    def _calculate_weights(self, merged: pd.DataFrame, active_codes) -> Dict[str, float]:
        active_codes = [code for code in active_codes if code]
        if not active_codes:
            return {}

        active_df = merged[merged["stock_code"].isin(active_codes)].copy()
        active_df = active_df.drop_duplicates(subset=["stock_code"], keep="last")
        if active_df.empty:
            return {code: 1.0 / len(active_codes) for code in active_codes}

        if self.weight_mode == "score" and "score" in active_df.columns:
            active_df["pos_score"] = active_df["score"].clip(lower=0.01)
            total_score = active_df["pos_score"].sum()
            if total_score > 0:
                return {
                    row["stock_code"]: float(row["pos_score"] / total_score)
                    for _, row in active_df.iterrows()
                }

        if self.weight_mode == "risk_parity" and "volatility" in active_df.columns:
            active_df["inv_vol"] = 1.0 / (active_df["volatility"] + 1e-9)
            total_inv_vol = active_df["inv_vol"].sum()
            if total_inv_vol > 0:
                return {
                    row["stock_code"]: float(row["inv_vol"] / total_inv_vol)
                    for _, row in active_df.iterrows()
                }

        return {code: 1.0 / len(active_codes) for code in active_codes}

    def generate_target_weights(
        self,
        date: str,
        day_data: pd.DataFrame,
        strategy_signals_df: pd.DataFrame,
        current_positions: Optional[Dict] = None,
    ) -> Dict[str, float]:
        raise NotImplementedError


class EventPolicy(BaseHoldingPolicy):
    def generate_target_weights(
        self,
        date: str,
        day_data: pd.DataFrame,
        strategy_signals_df: pd.DataFrame,
        current_positions: Optional[Dict] = None,
    ) -> Dict[str, float]:
        if strategy_signals_df.empty:
            return {}

        self._sync_actual_positions(current_positions)
        self._advance_holding_bars(date)
        merged = PositionManager.merge_signals(day_data, strategy_signals_df)
        if merged.empty:
            return {}

        negative_codes = set(merged[merged["signal"] == -1]["stock_code"].tolist())

        for code in list(self.holdings.keys()):
            if code in negative_codes:
                del self.holdings[code]

        buys_df = self._rank_candidates(merged[merged["signal"] == 1])
        for _, row in buys_df.iterrows():
            code = row["stock_code"]
            if code in self.holdings:
                continue
            if len(self.holdings) >= self.max_positions:
                break
            self.holdings[code] = HoldingInfo(
                code=code,
                entry_date=date,
                entry_price=float(row.get("open", 0.0) or 0.0),
            )

        for code in list(self.holdings.keys()):
            if self._is_expired(self.holdings[code], date):
                del self.holdings[code]

        return self._calculate_weights(merged, list(self.holdings.keys()))


class RankingPolicy(BaseHoldingPolicy):
    def generate_target_weights(
        self,
        date: str,
        day_data: pd.DataFrame,
        strategy_signals_df: pd.DataFrame,
        current_positions: Optional[Dict] = None,
    ) -> Dict[str, float]:
        if strategy_signals_df.empty:
            return {}

        self._sync_actual_positions(current_positions)
        self._advance_holding_bars(date)
        merged = PositionManager.merge_signals(day_data, strategy_signals_df)
        if merged.empty:
            return {}

        ranked_buys = self._rank_candidates(merged[merged["signal"] == 1]).head(self.max_positions)
        active_codes = ranked_buys["stock_code"].tolist()
        next_holdings: Dict[str, HoldingInfo] = {}
        for _, row in ranked_buys.iterrows():
            code = row["stock_code"]
            next_holdings[code] = self.holdings.get(
                code,
                HoldingInfo(
                    code=code,
                    entry_date=date,
                    entry_price=float(row.get("open", 0.0) or 0.0),
                ),
            )
        self.holdings = next_holdings
        return self._calculate_weights(merged, active_codes)


class StatefulPolicy(BaseHoldingPolicy):
    def generate_target_weights(
        self,
        date: str,
        day_data: pd.DataFrame,
        strategy_signals_df: pd.DataFrame,
        current_positions: Optional[Dict] = None,
    ) -> Dict[str, float]:
        if strategy_signals_df.empty:
            return {}

        self._sync_actual_positions(current_positions)
        self._advance_holding_bars(date)
        merged = PositionManager.merge_signals(day_data, strategy_signals_df)
        if merged.empty:
            return {}

        negative_codes = set(merged[merged["signal"] == -1]["stock_code"].tolist())
        expired_codes = {
            code for code, holding in self.holdings.items() if self._is_expired(holding, date)
        }
        for code in list(self.holdings.keys()):
            if code in negative_codes or code in expired_codes:
                del self.holdings[code]

        buys_df = self._rank_candidates(merged[merged["signal"] == 1])
        for _, row in buys_df.iterrows():
            code = row["stock_code"]
            if code in expired_codes:
                continue
            if code in self.holdings:
                continue
            if len(self.holdings) >= self.max_positions:
                break
            self.holdings[code] = HoldingInfo(
                code=code,
                entry_date=date,
                entry_price=float(row.get("open", 0.0) or 0.0),
            )

        return self._calculate_weights(merged, list(self.holdings.keys()))


class PositionManager:
    def __init__(
        self,
        max_positions: int = 5,
        weight_mode: str = "equal",
        max_hold_days: Optional[int] = None,
        strategy_spec: Optional[StrategySpec] = None,
    ):
        self.max_positions = max_positions
        self.weight_mode = weight_mode
        self.strategy_spec = strategy_spec
        self.last_decision_info: Dict[str, object] = {}
        self.max_hold_days = (
            max_hold_days
            if max_hold_days is not None
            else (strategy_spec.default_max_hold_days if strategy_spec is not None else None)
        )
        self.policy = self._build_policy()

    def _build_policy(self) -> BaseHoldingPolicy:
        signal_type = self.strategy_spec.signal_type if self.strategy_spec is not None else "stateful"
        holding_policy = (
            self.strategy_spec.holding_policy
            if self.strategy_spec is not None
            else "sell_on_minus_one"
        )
        policy_key = (signal_type, holding_policy)
        policy_map = {
            ("event", "timeout_exit"): EventPolicy,
            ("ranking", "hold_while_selected"): RankingPolicy,
            ("stateful", "sell_on_minus_one"): StatefulPolicy,
        }
        policy_cls = policy_map.get(policy_key)
        if policy_cls is None:
            raise ValueError(f"Unsupported strategy holding metadata: {policy_key}")

        resolved_hold_days = self.max_hold_days
        if signal_type == "event" and resolved_hold_days is None:
            resolved_hold_days = 1

        return policy_cls(
            max_positions=self.max_positions,
            weight_mode=self.weight_mode,
            max_hold_days=resolved_hold_days,
        )

    @property
    def holdings(self) -> Dict[str, HoldingInfo]:
        return self.policy.holdings

    def seed_holdings(self, holdings: Dict[str, HoldingInfo]) -> None:
        self.policy.holdings = dict(holdings or {})

    @staticmethod
    def merge_signals(day_data: pd.DataFrame, strategy_signals_df: pd.DataFrame) -> pd.DataFrame:
        clean_day_data = day_data.drop(columns=["signal", "score"], errors="ignore").copy()
        signal_cols = ["stock_code", "signal"]
        if "score" in strategy_signals_df.columns:
            signal_cols.append("score")
        merged = pd.merge(
            clean_day_data,
            strategy_signals_df[signal_cols],
            on="stock_code",
            how="inner",
        )
        return merged.drop_duplicates(subset=["stock_code"], keep="last")

    def generate_target_weights(
        self,
        date: str,
        day_data: pd.DataFrame,
        strategy_signals_df: pd.DataFrame,
        current_positions: Optional[Dict] = None,
    ) -> Dict[str, float]:
        target_weights = self.policy.generate_target_weights(
            date=date,
            day_data=day_data,
            strategy_signals_df=strategy_signals_df,
            current_positions=current_positions,
        )
        raw_signal_col = "raw_signal" if "raw_signal" in strategy_signals_df.columns else "signal"
        raw_signal_count = int(
            strategy_signals_df.loc[strategy_signals_df[raw_signal_col] == 1, "stock_code"].nunique()
        )
        selected_signal_count = len(target_weights)
        ranking_basis = (
            "score"
            if "score" in strategy_signals_df.columns and strategy_signals_df["score"].notna().any()
            else "stock_code"
        )
        self.last_decision_info = {
            "date": date,
            "raw_signal_count": raw_signal_count,
            "selected_signal_count": selected_signal_count,
            "selection_rate": float(selected_signal_count / raw_signal_count) if raw_signal_count > 0 else 0.0,
            "dropped_by_max_positions": max(0, raw_signal_count - selected_signal_count),
            "capacity_capped": raw_signal_count > selected_signal_count,
            "ranking_basis": ranking_basis,
            "selected_codes": list(target_weights.keys()),
            "current_positions_count": len(current_positions or {}),
            "max_positions": self.max_positions,
        }
        return target_weights
