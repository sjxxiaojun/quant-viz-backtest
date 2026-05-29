from pathlib import Path

import pandas as pd

from data_lake_update_service import DataLakeUpdateService


def test_data_freshness_uses_even_symbol_sample(tmp_path):
    symbols = [f"{idx:06d}" for idx in range(10)]
    for idx, symbol in enumerate(symbols):
        date = "2026-04-30" if idx >= 5 else "2026-04-29"
        pd.DataFrame({"date": [date]}).to_parquet(tmp_path / f"{symbol}_full_history.parquet", index=False)

    class FakeDataManager:
        def list_local_codes(self, asset_type):
            return symbols

        def get_cache_path(self, symbol):
            return Path(tmp_path) / f"{symbol}_full_history.parquet"

    service = DataLakeUpdateService(FakeDataManager())

    freshness = service.data_freshness(target_date="2026-04-30", max_scan=5)

    assert freshness["a_share"]["checked_count"] == 5
    assert freshness["a_share"]["fresh_count"] == 2
    assert freshness["score"] == 40.0
