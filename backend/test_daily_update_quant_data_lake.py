from __future__ import annotations

from pathlib import Path

import pandas as pd

import daily_update_quant_data_lake as daily_update
import download_a_share_market as a_share_dl


def _isolate_daily_update_paths(monkeypatch, tmp_path: Path) -> None:
    """把 daily_update 的所有数据来源路径隔离到 tmp_path。

    build_a_share_tasks 除了扫描 ROOT_DIR（数据湖）外，还会从 BACKEND_DIR/virtual_trading.db
    读取持仓股并强制并入 clean_universe；不隔离 BACKEND_DIR 会把真实持仓泄漏进测试。
    """
    monkeypatch.setattr(daily_update, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(daily_update, "BACKEND_DIR", tmp_path)


def _write_a_share_file(path: Path, code: str, dates: list[str], *, stock_name: str | None = None, columns=None):
    rows = []
    for idx, date in enumerate(dates):
        rows.append(
            {
                "date": date,
                "open": 10 + idx,
                "high": 10 + idx,
                "low": 10 + idx,
                "close": 10 + idx,
                "volume": 1000,
                "amount": 10000,
                "pct_chg": 0.0,
                "turn": 1.0,
                "tradestatus": "1",
                "pe": pd.NA,
                "pb": pd.NA,
                "ps": pd.NA,
                "pcf": pd.NA,
                "is_st": "0",
                "stock_code": code,
                "stock_name": stock_name or code,
            }
        )
    frame = pd.DataFrame(rows)
    if columns is not None:
        frame = frame[columns]
    frame.to_parquet(path, index=False)


def test_local_universe_does_not_block_eod_for_placeholder_names(monkeypatch, tmp_path):
    _isolate_daily_update_paths(monkeypatch, tmp_path)
    code = "600001"
    _write_a_share_file(tmp_path / f"{code}_full_history.parquet", code, ["2026-04-30"], stock_name=code)

    _clean_universe, tasks, summary = daily_update.build_a_share_tasks("2026-04-30", 7, 0, True)

    assert tasks == []
    assert summary["name_repair_skipped_local_universe"] == 1


def test_local_universe_stale_data_takes_priority_over_name_repair(monkeypatch, tmp_path):
    _isolate_daily_update_paths(monkeypatch, tmp_path)
    code = "600002"
    _write_a_share_file(tmp_path / f"{code}_full_history.parquet", code, ["2026-04-29"], stock_name=code)

    _clean_universe, tasks, _summary = daily_update.build_a_share_tasks("2026-04-30", 7, 0, True)

    assert len(tasks) == 1
    assert tasks[0]["code"] == code
    assert tasks[0]["reason"] == "stale"


def test_local_universe_schema_repair_still_runs(monkeypatch, tmp_path):
    _isolate_daily_update_paths(monkeypatch, tmp_path)
    code = "600003"
    missing_schema_column = [col for col in a_share_dl.STANDARD_COLUMNS if col != "pcf"]
    _write_a_share_file(
        tmp_path / f"{code}_full_history.parquet",
        code,
        ["2026-04-30"],
        stock_name=code,
        columns=missing_schema_column,
    )

    _clean_universe, tasks, _summary = daily_update.build_a_share_tasks("2026-04-30", 7, 0, True)

    assert len(tasks) == 1
    assert tasks[0]["code"] == code
    assert tasks[0]["reason"] == "schema"


def test_merge_frames_deduplication_and_type_coercion(tmp_path):
    code = "600004"
    existing_path = tmp_path / f"{code}_full_history.parquet"
    _write_a_share_file(existing_path, code, ["2026-04-28", "2026-04-29"], stock_name="OldName")

    incoming_df = pd.DataFrame(
        [
            {
                "date": "2026-04-29",
                "open": "12.5",
                "high": "13.0",
                "low": "12.0",
                "close": "12.8",
                "volume": "2000",
                "amount": "25000",
                "pct_chg": "1.5",
                "turn": "2.0",
                "tradestatus": 1,
                "pe": "18.5",
                "pb": "2.3",
                "ps": "3.1",
                "pcf": "9.4",
                "is_st": 0,
                "stock_code": code,
                "stock_name": "NewName",
            },
            {
                "date": "2026-04-30",
                "open": "12.8",
                "high": "13.5",
                "low": "12.7",
                "close": "13.2",
                "volume": "2200",
                "amount": "28000",
                "pct_chg": "3.1",
                "turn": "2.2",
                "tradestatus": 1,
                "pe": "19.0",
                "pb": "2.4",
                "ps": "3.2",
                "pcf": "9.6",
                "is_st": 0,
                "stock_code": code,
                "stock_name": "NewName",
            },
        ]
    )

    merged = daily_update.merge_frames(
        existing_path,
        incoming_df,
        a_share_dl.STANDARD_COLUMNS,
        code,
        "NewName",
    )

    assert len(merged) == 3
    assert list(merged["date"]) == ["2026-04-28", "2026-04-29", "2026-04-30"]
    # Check that keep='last' preserved the incoming updated row for 2026-04-29
    row_29 = merged[merged["date"] == "2026-04-29"].iloc[0]
    assert row_29["close"] == 12.8
    assert row_29["pe"] == 18.5
    assert row_29["stock_name"] == "NewName"

