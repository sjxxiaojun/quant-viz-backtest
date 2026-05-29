from __future__ import annotations

from pathlib import Path

import pandas as pd

import daily_update_quant_data_lake as daily_update
import download_a_share_market as a_share_dl


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
    monkeypatch.setattr(daily_update, "ROOT_DIR", tmp_path)
    code = "600001"
    _write_a_share_file(tmp_path / f"{code}_full_history.parquet", code, ["2026-04-30"], stock_name=code)

    _clean_universe, tasks, summary = daily_update.build_a_share_tasks("2026-04-30", 7, 0, True)

    assert tasks == []
    assert summary["name_repair_skipped_local_universe"] == 1


def test_local_universe_stale_data_takes_priority_over_name_repair(monkeypatch, tmp_path):
    monkeypatch.setattr(daily_update, "ROOT_DIR", tmp_path)
    code = "600002"
    _write_a_share_file(tmp_path / f"{code}_full_history.parquet", code, ["2026-04-29"], stock_name=code)

    _clean_universe, tasks, _summary = daily_update.build_a_share_tasks("2026-04-30", 7, 0, True)

    assert len(tasks) == 1
    assert tasks[0]["code"] == code
    assert tasks[0]["reason"] == "stale"


def test_local_universe_schema_repair_still_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(daily_update, "ROOT_DIR", tmp_path)
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
