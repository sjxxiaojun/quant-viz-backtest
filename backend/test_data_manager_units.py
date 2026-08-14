"""数据口径回归测试：成交量单位统一、ST 来源标记、代理环境无副作用、帧缓存策略、qfq attrs。"""

import os

import numpy as np
import pandas as pd
import pytest

import data_manager as dm
from data_manager import DataManager, _no_proxy_environment


def _manager(tmp_path, **kwargs):
    return DataManager(cache_dir=str(tmp_path / "cache"), **kwargs)


def _dates(n, start="2024-01-02"):
    return pd.bdate_range(start, periods=n).strftime("%Y-%m-%d").tolist()


def _akshare_style_frame(dates, close=10.0, volume_hand=5000.0):
    """AKShare 风格：中文列名，成交量单位为手，成交额单位为元。"""
    return pd.DataFrame(
        {
            "日期": dates,
            "开盘": close,
            "收盘": close,
            "最高": close * 1.02,
            "最低": close * 0.98,
            "成交量": volume_hand,
            "成交额": volume_hand * 100.0 * close,
            "涨跌幅": 0.5,
        }
    )


def _baostock_style_frame(dates, close=10.0, volume_share=500000.0, is_st=0):
    """Baostock 风格：volume 单位为股，含按日 isST。"""
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "close": close,
            "high": close * 1.02,
            "low": close * 0.98,
            "volume": volume_share,
            "amount": volume_share * close,
            "pctChg": 0.5,
            "isST": is_st,
            "stock_code": "600000",
            "stock_name": "测试股",
        }
    )


# ---------------------------------------------------------------------------
# 1. 成交量单位统一
# ---------------------------------------------------------------------------

def test_akshare_volume_hand_converted_to_share(tmp_path):
    manager = _manager(tmp_path)
    raw = _akshare_style_frame(_dates(5), close=10.0, volume_hand=5000.0)

    normalized = manager._normalize_market_frame("600000", raw, source="AKSHARE")

    assert (normalized["volume"] == 500000.0).all()
    assert normalized.attrs["volume_unit"] == "share"


def test_baostock_volume_share_not_scaled(tmp_path):
    manager = _manager(tmp_path)
    raw = _baostock_style_frame(_dates(5), close=10.0, volume_share=500000.0)

    normalized = manager._normalize_market_frame("600000", raw, source="BAOSTOCK")

    assert (normalized["volume"] == 500000.0).all()


def test_source_tag_takes_priority_over_amount_ratio_with_warning(tmp_path, caplog):
    """源标注优先于比值启发式：标注说"手"就按手换算，比值只允许告警不允许覆盖。

    amount/(close*volume) ≈ qfq 复权因子 × 单位倍数——amount 不复权而 close 是前复权，
    比值本身就受复权因子污染，让它压过源标注就是把"复权深度"误读成"单位"。
    """
    manager = _manager(tmp_path)
    dates = _dates(5)
    raw = _akshare_style_frame(dates, close=10.0, volume_hand=500000.0)
    raw["成交额"] = 500000.0 * 10.0  # 比值 = 1

    with caplog.at_level("WARNING", logger="DataManager"):
        normalized = manager._normalize_market_frame("600000", raw, source="AKSHARE")

    # 标注为 AKSHARE(手) -> 必须 ×100，不得被比值反转
    assert (normalized["volume"] == 50000000.0).all()
    assert any("成交量单位校验" in record.message for record in caplog.records)
    assert any("以数据源标注为准" in record.message for record in caplog.records)


def test_baostock_source_tag_not_scaled_even_when_ratio_looks_like_lots(tmp_path, caplog):
    # 标注为 BAOSTOCK(股) 时，即使比值 ≈100 也不得 ×100（只告警）
    manager = _manager(tmp_path)
    raw = _baostock_style_frame(_dates(5), close=10.0, volume_share=500000.0)
    raw["amount"] = 500000.0 * 10.0 * 100.0  # 比值 = 100

    with caplog.at_level("WARNING", logger="DataManager"):
        normalized = manager._normalize_market_frame("600000", raw, source="BAOSTOCK")

    assert (normalized["volume"] == 500000.0).all()
    assert any("成交量单位校验" in record.message for record in caplog.records)


def _deep_adjust_share_frame(dates, raw_close, factor, volume_share):
    """真实口径的深度前复权帧：close 是 qfq 价，volume/amount 是不复权口径（股/元）。"""
    raw_close = np.asarray(raw_close, dtype=float)
    factor = np.asarray(factor, dtype=float)
    volume_share = np.asarray(volume_share, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "stock_code": "600000",
            "open": raw_close / factor,
            "high": raw_close / factor * 1.01,
            "low": raw_close / factor * 0.99,
            "close": raw_close / factor,        # 前复权价
            "volume": volume_share,             # 股（不复权）
            "amount": raw_close * volume_share,  # 元（不复权）
        }
    )


def test_deep_adjusted_share_frame_not_scaled_and_warns(tmp_path, caplog):
    """复权因子 >= 10 的"股"数据必须原样保留：旧实现会把它 ×100 造成静默百倍污染。

    amount/(close*volume) 在这里 ≈ 12，旧的"比值 >= 10 判手"会命中；
    新实现的可靠证据只有"比值小"，比值 12 落在不确定区间 -> 告警 + 不换算。
    """
    manager = _manager(tmp_path)
    dates = _dates(30)
    raw_close = np.linspace(60.0, 66.0, 30)
    frame = _deep_adjust_share_frame(dates, raw_close, factor=12.0, volume_share=1_000_000.0)

    with caplog.at_level("WARNING", logger="DataManager"):
        normalized = manager._normalize_market_frame("600000", frame)

    assert (normalized["volume"] == 1_000_000.0).all()
    assert any("成交量单位无法判定" in record.message for record in caplog.records)


def test_deep_adjusted_frame_with_qfq_anchor_tail_keeps_shares(tmp_path):
    """全历史帧的帧尾复权因子恒为 1，据此可靠锚定"股"并沿段传播到深度复权的早期行。"""
    manager = _manager(tmp_path)
    dates = _dates(60)
    # 复权因子从 15 逐段回落到 1（送转/分红的真实形态：qfq 基准日在帧尾）
    factor = np.concatenate([np.full(20, 15.0), np.full(20, 4.0), np.full(20, 1.0)])
    raw_close = np.linspace(50.0, 80.0, 60)
    frame = _deep_adjust_share_frame(dates, raw_close, factor=factor, volume_share=2_000_000.0)

    normalized = manager._normalize_market_frame("600000", frame)

    assert (normalized["volume"] == 2_000_000.0).all()


def test_mixed_units_inside_deep_adjusted_frame_still_detected(tmp_path):
    """深度复权 + 帧内混单位：靠不复权价的 100 倍台阶识别"手"行，不靠受复权污染的比值。"""
    manager = _manager(tmp_path)
    dates = _dates(60)
    factor = np.concatenate([np.full(30, 15.0), np.full(30, 1.0)])
    raw_close = np.linspace(50.0, 80.0, 60)
    frame = _deep_adjust_share_frame(dates, raw_close, factor=factor, volume_share=2_000_000.0)
    # 第 10~19 行来自 AKShare 增量（手）：volume 变成 1/100，amount 不变
    frame.loc[10:19, "volume"] = 20_000.0

    normalized = manager._normalize_market_frame("600000", frame)

    assert (normalized["volume"] == 2_000_000.0).all()


def test_mixed_unit_rows_scaled_per_row(tmp_path):
    # 同一标的历史上混有 akshare(手) 与 baostock(股) 行时，按行判别后统一为股
    manager = _manager(tmp_path)
    dates = _dates(6)
    hand_rows = pd.DataFrame(
        {
            "date": dates[:3],
            "close": 10.0,
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "volume": 5000.0,          # 手
            "amount": 5000.0 * 100.0 * 10.0,
        }
    )
    share_rows = pd.DataFrame(
        {
            "date": dates[3:],
            "close": 10.0,
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "volume": 500000.0,        # 股
            "amount": 500000.0 * 10.0,
        }
    )
    raw = pd.concat([hand_rows, share_rows], ignore_index=True)

    normalized = manager._normalize_market_frame("600000", raw)

    assert (normalized["volume"] == 500000.0).all()


def test_legacy_parquet_converted_on_read_without_rewriting_disk(tmp_path):
    # 数据湖存量 parquet 是"手"单位：读取路径换算为股，但磁盘文件保持原样
    manager = _manager(tmp_path)
    dates = _dates(5)
    legacy = pd.DataFrame(
        {
            "date": dates,
            "stock_code": "600000",
            "stock_name": "测试股",
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "close": 10.0,
            "volume": 5000.0,                     # 手
            "amount": 5000.0 * 100.0 * 10.0,       # 元
            "pct_chg": 0.5,
        }
    )
    cache_path = manager.get_cache_path("600000")
    legacy.to_parquet(cache_path, index=False)
    mtime_before = cache_path.stat().st_mtime_ns

    frame = manager._read_cached_frame("600000")

    assert (frame["volume"] == 500000.0).all()
    on_disk = pd.read_parquet(cache_path)
    assert (on_disk["volume"] == 5000.0).all()
    assert cache_path.stat().st_mtime_ns == mtime_before


def test_read_cached_frame_honours_cache_unit_tag(tmp_path):
    """回测主路径 _read_cached_frame 必须把缓存自带的单位标注传下去，且标注优先于比值。"""
    manager = _manager(tmp_path)
    dates = _dates(5)
    cached = pd.DataFrame(
        {
            "date": dates,
            "stock_code": "600000",
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "close": 10.0,
            "volume": 5000.0,
            "amount": 5000.0 * 10.0,   # 比值 = 1，只看比值会判成"股"
            "volume_unit": "lot",      # 但缓存明确标注单位是"手"
        }
    )
    cached.to_parquet(manager.get_cache_path("600000"), index=False)

    frame = manager._read_cached_frame("600000")

    assert (frame["volume"] == 500000.0).all()


def test_read_cached_frame_share_tag_blocks_ratio_upscaling(tmp_path):
    """缓存标注"股"时，即使比值 ≈100 也不得 ×100（这正是深度复权标的的静默污染入口）。"""
    manager = _manager(tmp_path)
    dates = _dates(5)
    cached = pd.DataFrame(
        {
            "date": dates,
            "stock_code": "600000",
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "close": 10.0,
            "volume": 500000.0,
            "amount": 500000.0 * 10.0 * 100.0,  # 比值 = 100
            "volume_unit": "share",
        }
    )
    cached.to_parquet(manager.get_cache_path("600000"), index=False)

    frame = manager._read_cached_frame("600000")

    assert (frame["volume"] == 500000.0).all()


def test_pool_frame_volume_unit_inference(tmp_path):
    manager = _manager(tmp_path)
    dates = _dates(5)
    raw = pd.DataFrame(
        {
            "date": dates,
            "stock_code": "000001",
            "close": 20.0,
            "open": 20.0,
            "high": 20.4,
            "low": 19.6,
            "volume": 3000.0,                    # 手
            "amount": 3000.0 * 100.0 * 20.0,
        }
    )

    normalized = manager._normalize_pool_market_frame(raw)

    assert (normalized["volume"] == 300000.0).all()
    assert normalized.attrs["volume_unit"] == "share"


def test_undeterminable_rows_follow_source_tag(tmp_path):
    # amount 缺失无法判别时，回退到数据源标注（AKSHARE -> ×100）
    manager = _manager(tmp_path)
    raw = _akshare_style_frame(_dates(5), close=10.0, volume_hand=5000.0)
    raw["成交额"] = np.nan

    normalized = manager._normalize_market_frame("600000", raw, source="AKSHARE")

    assert (normalized["volume"] == 500000.0).all()


def test_unit_conversion_idempotent_after_merge(tmp_path, monkeypatch):
    # 缓存(读取时已换算) + 增量抓取(fetch 时已换算) 合并后不得二次换算
    manager = _manager(tmp_path)
    dates = _dates(10)
    legacy = pd.DataFrame(
        {
            "date": dates[:5],
            "stock_code": "600000",
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "close": 10.0,
            "volume": 5000.0,
            "amount": 5000.0 * 100.0 * 10.0,
        }
    )
    legacy.to_parquet(manager.get_cache_path("600000"), index=False)

    cached = manager._read_cached_frame("600000")
    fetched = manager._normalize_market_frame(
        "600000", _akshare_style_frame(dates[5:], close=10.0, volume_hand=5000.0), source="AKSHARE"
    )
    merged = manager._merge_and_save_cache("600000", cached, fetched)

    assert (merged["volume"] == 500000.0).all()
    reread = manager._read_cached_frame("600000")
    assert (reread["volume"] == 500000.0).all()


# ---------------------------------------------------------------------------
# 2. ST 历史状态透传与来源标记
# ---------------------------------------------------------------------------

def test_baostock_daily_is_st_passthrough_with_source_tag(tmp_path):
    manager = _manager(tmp_path)
    dates = _dates(4)
    raw = _baostock_style_frame(dates, is_st=[0, 1, 1, 0])

    normalized = manager._normalize_market_frame("600000", raw, source="BAOSTOCK")

    assert normalized["is_st"].tolist() == [0, 1, 1, 0]
    assert (normalized["st_source"] == "baostock_daily").all()


def test_akshare_missing_is_st_filled_zero_with_missing_tag(tmp_path):
    manager = _manager(tmp_path)
    raw = _akshare_style_frame(_dates(4))

    normalized = manager._normalize_market_frame("600000", raw, source="AKSHARE")

    assert (normalized["is_st"] == 0).all()
    assert (normalized["st_source"] == "missing").all()


def test_legacy_cache_is_st_tagged_unknown(tmp_path):
    # 存量缓存已有 is_st 列但无来源信息：标 unknown，不得冒充真实 ST 状态
    manager = _manager(tmp_path)
    raw = _baostock_style_frame(_dates(4), is_st=0)

    normalized = manager._normalize_market_frame("600000", raw, source=None)

    assert (normalized["st_source"] == "unknown").all()


def test_st_source_column_survives_merge(tmp_path):
    manager = _manager(tmp_path)
    dates = _dates(8)
    bs_part = manager._normalize_market_frame(
        "600000", _baostock_style_frame(dates[:4], is_st=1), source="BAOSTOCK"
    )
    ak_part = manager._normalize_market_frame(
        "600000", _akshare_style_frame(dates[4:]), source="AKSHARE"
    )

    merged = manager._merge_and_save_cache("600000", bs_part, ak_part)

    merged = merged.sort_values("date").reset_index(drop=True)
    assert merged.loc[:3, "st_source"].tolist() == ["baostock_daily"] * 4
    assert merged.loc[4:, "st_source"].tolist() == ["missing"] * 4
    assert merged.loc[:3, "is_st"].tolist() == [1, 1, 1, 1]


def test_pool_frame_st_source_missing_when_column_absent(tmp_path):
    manager = _manager(tmp_path)
    raw = pd.DataFrame(
        {
            "date": _dates(3),
            "stock_code": "000001",
            "close": 10.0,
            "volume": 1000.0,
            "amount": 10000.0,
        }
    )

    normalized = manager._normalize_pool_market_frame(raw)

    assert (normalized["st_source"] == "missing").all()


# ---------------------------------------------------------------------------
# 3. 代理环境变量无进程级副作用
# ---------------------------------------------------------------------------

def test_init_does_not_mutate_proxy_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7890")
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:7890")
    monkeypatch.delenv("no_proxy", raising=False)

    _manager(tmp_path)

    assert os.environ["http_proxy"] == "http://127.0.0.1:7890"
    assert os.environ["https_proxy"] == "http://127.0.0.1:7890"
    assert os.environ["all_proxy"] == "socks5://127.0.0.1:7890"
    assert "no_proxy" not in os.environ


def test_no_proxy_environment_scoped_and_restored(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")
    monkeypatch.delenv("no_proxy", raising=False)

    with _no_proxy_environment():
        assert os.environ.get("no_proxy") == "*"
        assert "http_proxy" not in os.environ

    assert os.environ["http_proxy"] == "http://127.0.0.1:7890"
    assert "no_proxy" not in os.environ


# ---------------------------------------------------------------------------
# 4. 帧缓存：只读共享帧 + 参数化 LRU 淘汰
# ---------------------------------------------------------------------------

def _write_symbol_parquet(manager, symbol, dates):
    frame = pd.DataFrame(
        {
            "date": dates,
            "stock_code": symbol,
            "close": 10.0,
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "volume": 1000.0,
            "amount": 10000.0,
        }
    )
    frame.to_parquet(manager.get_cache_path(symbol), index=False)


def test_cached_frame_read_returns_shared_object_without_copy(tmp_path):
    manager = _manager(tmp_path)
    _write_symbol_parquet(manager, "600000", _dates(5))

    first = manager._read_cached_frame("600000")
    second = manager._read_cached_frame("600000")

    assert first is second


def test_public_get_stock_data_returns_independent_copy(tmp_path):
    # 对外出口必须是独立副本：调用方修改不能污染缓存
    manager = _manager(tmp_path)
    dates = _dates(5)
    _write_symbol_parquet(manager, "600000", dates)

    df, source = manager.get_stock_data("600000", dates[0], dates[-1], allow_mock=False)
    assert source == "CACHE"
    df.loc[:, "close"] = -1.0

    cached = manager._read_cached_frame("600000")
    assert (cached["close"] == 10.0).all()


def test_frame_cache_max_entries_parameterized_and_lru_eviction(tmp_path):
    manager = _manager(tmp_path, frame_cache_max_entries=2, frame_cache_eviction="lru")
    dates = _dates(5)
    for symbol in ("600000", "600001", "600002"):
        _write_symbol_parquet(manager, symbol, dates)

    a = manager._read_cached_frame("600000")
    manager._read_cached_frame("600001")
    manager._read_cached_frame("600000")  # 命中 -> 600000 变为最近使用
    manager._read_cached_frame("600002")  # 插入 -> 淘汰最久未使用的 600001

    keys = list(manager._frame_cache.keys())
    assert str(manager.get_cache_path("600000")) in keys
    assert str(manager.get_cache_path("600002")) in keys
    assert str(manager.get_cache_path("600001")) not in keys
    # LRU 命中不失效：再次读取仍是同一共享对象
    assert manager._read_cached_frame("600000") is a


def test_frame_cache_fifo_eviction_ignores_hits(tmp_path):
    manager = _manager(tmp_path, frame_cache_max_entries=2, frame_cache_eviction="fifo")
    dates = _dates(5)
    for symbol in ("600000", "600001", "600002"):
        _write_symbol_parquet(manager, symbol, dates)

    manager._read_cached_frame("600000")
    manager._read_cached_frame("600001")
    manager._read_cached_frame("600000")  # FIFO 下命中不改变淘汰顺序
    manager._read_cached_frame("600002")  # 淘汰最先插入的 600000

    keys = list(manager._frame_cache.keys())
    assert str(manager.get_cache_path("600000")) not in keys
    assert str(manager.get_cache_path("600001")) in keys


def test_frame_cache_max_entries_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_FRAME_CACHE_MAX_ENTRIES", "7")
    monkeypatch.setenv("QUANT_FRAME_CACHE_EVICTION", "fifo")

    manager = _manager(tmp_path)

    assert manager._frame_cache_max_entries == 7
    assert manager._frame_cache_eviction == "fifo"


# ---------------------------------------------------------------------------
# 5. qfq 口径标注
# ---------------------------------------------------------------------------

def test_normalized_frame_carries_qfq_attrs(tmp_path):
    manager = _manager(tmp_path)
    normalized = manager._normalize_market_frame(
        "600000", _akshare_style_frame(_dates(3)), source="AKSHARE"
    )

    assert normalized.attrs["adjust"] == "qfq"
    assert "涨跌停" in normalized.attrs["adjust_note"]
    assert normalized.attrs["volume_unit"] == "share"


def test_get_stock_data_result_carries_qfq_attrs(tmp_path):
    manager = _manager(tmp_path)
    dates = _dates(5)
    _write_symbol_parquet(manager, "600000", dates)

    df, _ = manager.get_stock_data("600000", dates[0], dates[-1], allow_mock=False)

    assert df.attrs.get("adjust") == "qfq"
    assert df.attrs.get("volume_unit") == "share"
