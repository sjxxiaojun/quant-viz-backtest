"""行情数据接入与本地数据湖读取。

数据口径约定（引擎/策略侧必须知晓）：

1. 复权方式 adjust='qfq'（前复权）：AKShare 用 adjust="qfq"、Baostock 用 adjustflag="2"。
   qfq 价格以下载日为基准动态重算，因此：
   - 除权除息日相邻两日的 qfq 价格比值不等于交易所真实涨跌幅，基于
     open/prev_close 比值的涨跌停判定在除权除息日会失真；
   - 数据湖每次刷新后历史价格可能整体变化，回测结果对下载日期敏感；
   - 现金分红在 qfq 语义下等价于自动再投资。
   返回帧的 frame.attrs["adjust"] == "qfq"、frame.attrs["adjust_note"] 记录该口径，
   供引擎层（涨跌停判定等）读取并做相应处理。

2. 成交量单位统一为"股"：AKShare 系接口原始单位为"手"（1 手 = 100 股），
   Baostock 为"股"。判别优先级为 **源标注 > 兜底启发式**：
   - 有数据源/缓存单位标注时一律按标注换算，amount/(close*volume) 比值只用于
     记 WARNING，不允许反过来覆盖标注（该比值 ≈ qfq 复权因子 × 单位倍数，
     复权因子 >= 10 的长历史高送转标的会被它误判成"手"并 ×100）；
   - 无标注时才启用兜底判别，判据与复权无关：用不复权成交均价 amount/volume 的
     ~100 倍台阶切分"单位一致段"，用"比值 <= 5"这类可靠证据（复权因子恒 >= 1，
     故只有'比值小'能证明单位是股）锚定后沿段传播；
   - 判不出来时记 WARNING 并保持原样，绝不静默换算。
   磁盘上的存量 parquet 保持原样，仅在读取时换算。
   返回帧的 frame.attrs["volume_unit"] == "share"。

3. ST 状态 is_st：仅 Baostock 提供按日 isST 字段；AKShare 源缺失时补 0。
   帧上的 st_source 列按行标记来源：
   - "baostock_daily"：真实按日 ST 状态；
   - "missing"：源数据不含 ST 字段，is_st==0 不代表非 ST；
   - "unknown"：存量缓存无法回溯来源。
   引擎层应据此区分"真无 ST"与"数据缺失"。
"""

import pandas as pd
import numpy as np
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timedelta
import os
import logging
from pathlib import Path
import threading
from typing import Dict, List, Optional, Tuple
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DataManager")

# 代理环境变量仅在向上游发起请求的窗口内临时禁用（AKShare 走系统代理时常见 ProxyError），
# 请求结束后必须恢复原值，不允许污染进程级环境。
_PROXY_ENV_KEYS = (
    "no_proxy", "NO_PROXY",
    "http_proxy", "HTTP_PROXY",
    "https_proxy", "HTTPS_PROXY",
    "all_proxy", "ALL_PROXY",
)


@contextmanager
def _no_proxy_environment():
    saved = {key: os.environ.get(key) for key in _PROXY_ENV_KEYS}
    try:
        os.environ["no_proxy"] = "*"
        os.environ["NO_PROXY"] = "*"
        for key in _PROXY_ENV_KEYS:
            if key.lower() == "no_proxy":
                continue
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

_AKSHARE = None
_BAOSTOCK = None
_IMPORT_LOCK = threading.Lock()


def _get_akshare():
    global _AKSHARE
    if _AKSHARE is None:
        with _IMPORT_LOCK:
            if _AKSHARE is None:
                import akshare as ak

                _AKSHARE = ak
    return _AKSHARE


def _get_baostock():
    global _BAOSTOCK
    if _BAOSTOCK is None:
        with _IMPORT_LOCK:
            if _BAOSTOCK is None:
                import baostock as bs

                _BAOSTOCK = bs
    return _BAOSTOCK

ETF_PREFIXES = (
    "159",
    "510",
    "511",
    "512",
    "513",
    "515",
    "516",
    "517",
    "518",
    "520",
    "526",
    "530",
    "551",
    "560",
    "561",
    "562",
    "563",
    "588",
    "589",
)

CACHE_EDGE_TOLERANCE_DAYS = 7
LATEST_MARKET_CACHE_TTL_SECONDS = 300
# A股 1 手 = 100 股；AKShare 系日线接口成交量单位为"手"，Baostock 为"股"
VOLUME_LOT_SIZE = 100.0
# 数据源/缓存单位标注 -> 成交量原始单位换算到"股"的倍数。
# 这是成交量单位判别的**第一优先级**：能解析出标注就按标注走，比值启发式只做无标注兜底。
# 注意：AKSHARE_SINA（fund_etf_hist_sina）的成交量单位未经核实，故意不列入——
# 宁可走兜底启发式，也不要凭猜测写死一个可能错 100 倍的标注。
VOLUME_SOURCE_EXPECTED_SCALE = {
    "AKSHARE": VOLUME_LOT_SIZE,      # 东财日线：手
    "AKSHARE_EM": VOLUME_LOT_SIZE,
    "BAOSTOCK": 1.0,                 # 股
    "MOCK": 1.0,
    "CACHE_SHARE": 1.0,              # 缓存文件自带"已归一为股"的单位标注
    "CACHE_LOT": VOLUME_LOT_SIZE,    # 缓存文件自带"手"的单位标注
}
# 缓存帧里可能携带单位/来源标注的列（按优先级排列）。
# 只认"单位语义"的列：读取路径会把已归一化为股的帧写回磁盘，
# 通用 provenance 列（source/data_source）描述的是"数据从哪来"而非"盘上存的是什么单位"，
# 直接拿来换算会在"已归一化 + 标注仍写 AKSHARE"时造成二次 ×100。
VOLUME_UNIT_HINT_COLUMNS = ("volume_unit", "volume_source")
VOLUME_UNIT_HINT_ALIASES = {
    "SHARE": "CACHE_SHARE",
    "SHARES": "CACHE_SHARE",
    "股": "CACHE_SHARE",
    "LOT": "CACHE_LOT",
    "HAND": "CACHE_LOT",
    "手": "CACHE_LOT",
}
# ---- 无源标注时的兜底判据阈值 ----
# amount/(close*volume) ≈ 复权因子 × 单位倍数。qfq 复权因子恒 >= 1（送转/分红只会摊薄），
# 所以"比值小"是可靠证据、"比值大"不是：比值 30 既可能是手(因子 0.3，不可能)，
# 也可能是深度复权的股(因子 30)。因此只把"比值小"当作可靠锚点。
VOLUME_UNIT_SHARE_MAX_RATIO = 5.0
# 帧内找不到任何可靠"股"锚点时，才允许低置信度判为"手"，并且必须记 WARNING。
# 门槛卡在"整段中位比值"落在 [50, 500]：手 + 复权因子 1~5 才会长这样；
# 复权因子 10~40 的"股"数据中位比值只有 10~40，落不进来，因而不会被误判 ×100。
VOLUME_UNIT_LOT_MIN_RATIO = 50.0
VOLUME_UNIT_LOT_MAX_RATIO = 500.0
# 1 手 = 100 股 -> 不复权成交均价(amount/volume)在单位切换处出现 10^2 的台阶
VOLUME_UNIT_STEP_LOG10 = 2.0
# 台阶识别容差：除权跳空至多数倍(log10 <= 0.7)、涨跌停至多 30%，都落在 [1.3, 2.7] 之外
VOLUME_UNIT_STEP_TOLERANCE = 0.7
FRAME_CACHE_MAX_ENTRIES_DEFAULT = 1024
FRAME_CACHE_EVICTION_DEFAULT = "lru"  # 支持 lru / fifo
ADJUST_NOTE = (
    "qfq 前复权价：除权除息日相邻两日价格比值不等于交易所真实涨跌幅，"
    "涨跌停判定应以不复权 prev_close（除权参考价）为准；"
    "qfq 以下载日为基准动态重算，历史价格随数据刷新变化。"
)
NORMALIZED_NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pct_chg",
    "turn",
    "turnover_rate",
    "pe",
    "pb",
    "ps",
    "pcf",
    "amplitude",
    "prev_close",
    "intraday_ret",
    "open_gap",
]
PRETTY_NAMES = {
    "510300": "沪深300ETF", "510500": "中证500ETF", "510050": "上证50ETF",
    "159915": "创业板ETF", "159919": "300ETF(深)", "512660": "军工ETF",
    "512010": "医药ETF", "512880": "证券ETF", "512480": "半导体ETF",
    "515030": "新能源车ETF", "510880": "红利ETF", "159928": "消费ETF",
    "518880": "黄金ETF", "513100": "纳指ETF",
    "600519": "贵州茅台", "000858": "五粮液", "600036": "招商银行",
    "601318": "中国平安", "601012": "隆基绿能", "300750": "宁德时代",
    "002594": "比亚迪", "600030": "中信证券", "000001": "平安银行",
}


class DataFetchError(RuntimeError):
    def __init__(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        *,
        cache_start: Optional[str] = None,
        cache_end: Optional[str] = None,
        attempted_sources: Optional[list[str]] = None,
    ):
        self.symbol = symbol
        self.start_date = start_date
        self.end_date = end_date
        self.cache_start = cache_start
        self.cache_end = cache_end
        self.attempted_sources = attempted_sources or []
        cache_desc = (
            f"本地缓存覆盖 {cache_start} 至 {cache_end}"
            if cache_start and cache_end
            else "本地缓存无可用覆盖"
        )
        source_desc = " -> ".join(self.attempted_sources) if self.attempted_sources else "无可用上游源"
        super().__init__(
            f"{symbol} 在 {start_date} 至 {end_date} 区间无法补齐真实行情数据。{cache_desc}；尝试来源: {source_desc}"
        )


class PoolDataFetchError(RuntimeError):
    def __init__(self, failures: Dict[str, str], start_date: str, end_date: str):
        self.failures = failures
        self.start_date = start_date
        self.end_date = end_date
        preview = "; ".join(
            f"{symbol}: {message}" for symbol, message in list(failures.items())[:3]
        )
        if len(failures) > 3:
            preview = f"{preview}; 其余 {len(failures) - 3} 只标的同样失败"
        super().__init__(
            f"股票池在 {start_date} 至 {end_date} 区间无法完成真实数据加载，共 {len(failures)} 只标的失败。{preview}"
        )

class DataManager:
    def __init__(
        self,
        cache_dir="./quant_data_lake",
        frame_cache_max_entries: Optional[int] = None,
        frame_cache_eviction: Optional[str] = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.etf_cache_dir = self.cache_dir / "etf"
        self.etf_cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_sync_date = None
        self._baostock_lock = threading.Lock()
        self._local_codes_cache = {}
        self._local_codes_cache_ts = {}
        self._latest_market_cache = None
        self._latest_market_cache_ts = 0.0
        # 帧缓存返回共享只读帧：所有对外路径必须经 _filter_by_range 等复制后再交给调用方，
        # 任何调用方不得原地修改 _frame_cache 中的对象。
        self._frame_cache = OrderedDict()
        self._cache_window_cache = {}
        self._stock_name_cache = {}
        self._symbol_selection_cache = {}
        self._last_symbol_selection_metadata = {}
        self._last_pool_quality = {}
        self._trading_calendar_cache = {}
        self._frame_cache_lock = threading.Lock()
        self._cache_write_locks = {}
        self._cache_write_locks_lock = threading.Lock()
        if frame_cache_max_entries is None:
            frame_cache_max_entries = int(
                os.environ.get("QUANT_FRAME_CACHE_MAX_ENTRIES", str(FRAME_CACHE_MAX_ENTRIES_DEFAULT))
            )
        self._frame_cache_max_entries = max(1, int(frame_cache_max_entries))
        eviction = (
            frame_cache_eviction
            or os.environ.get("QUANT_FRAME_CACHE_EVICTION", FRAME_CACHE_EVICTION_DEFAULT)
        ).strip().lower()
        if eviction not in ("lru", "fifo"):
            eviction = FRAME_CACHE_EVICTION_DEFAULT
        self._frame_cache_eviction = eviction
        self.api_url = os.environ.get("DATA_LAKE_API_URL")

    def _frame_cache_touch_locked(self, cache_key):
        # LRU 语义下命中即移动到队尾；FIFO 保持插入序，淘汰始终从队首开始
        if self._frame_cache_eviction == "lru":
            try:
                self._frame_cache.move_to_end(cache_key)
            except KeyError:
                pass

    def _frame_cache_store_locked(self, cache_key, value):
        self._frame_cache.pop(cache_key, None)
        while len(self._frame_cache) >= self._frame_cache_max_entries:
            self._frame_cache.popitem(last=False)
        self._frame_cache[cache_key] = value

    def get_market_status(self):
        """
        Check if today is a trading day and if data is likely available.
        """
        now = datetime.now()
        if now.weekday() >= 5: return "休市 (周末)"
        if now.hour < 16: return f"交易中 (上次同步: {(now - timedelta(days=1)).strftime('%Y-%m-%d')})"
        return "数据就绪 (今日已收盘)"

    def _get_bs_symbol(self, symbol):
        """
        Convert standard symbol (e.g., 000001) to Baostock format (e.g., sz.000001).
        """
        if not symbol: return ""
        if symbol.startswith(('92', '4', '8', '43', '83', '87', '88', '89')): return f"bj.{symbol}"
        if symbol.startswith(('6', '5', '11')): return f"sh.{symbol}"
        elif symbol.startswith(('0', '3', '2')): return f"sz.{symbol}"
        return f"sz.{symbol}"

    def _normalize_symbol(self, symbol):
        text = str(symbol or "").strip()
        # Remove exchange prefix if present (e.g., "sz.000001" -> "000001")
        if '.' in text:
            text = text.split('.')[-1]
        return text.zfill(6) if text.isdigit() and len(text) < 6 else text

    def is_etf_symbol(self, symbol):
        symbol = self._normalize_symbol(symbol)
        return symbol.startswith(ETF_PREFIXES)

    def get_cache_path(self, symbol):
        symbol = self._normalize_symbol(symbol)
        if self.is_etf_symbol(symbol):
            return self.etf_cache_dir / f"{symbol}_full_history.parquet"
        return self.cache_dir / f"{symbol}_full_history.parquet"

    def get_stock_name(self, symbol) -> str:
        symbol = self._normalize_symbol(symbol)
        if symbol in PRETTY_NAMES:
            return PRETTY_NAMES[symbol]
        cached = self._stock_name_cache.get(symbol)
        if cached:
            return cached

        cache_path = self.get_cache_path(symbol)
        name = symbol
        if cache_path.exists():
            try:
                import pyarrow.parquet as pq

                schema = set(pq.read_schema(cache_path).names)
                if "stock_name" in schema:
                    columns = ["stock_name"]
                    if "date" in schema:
                        columns.append("date")
                    frame = pd.read_parquet(cache_path, columns=columns)
                    if not frame.empty:
                        if "date" in frame.columns:
                            frame = frame.sort_values("date")
                        names = frame["stock_name"].dropna().astype(str).str.strip()
                        names = names[(names != "") & (names != symbol)]
                        if not names.empty:
                            name = names.iloc[-1]
            except Exception as exc:
                logger.debug(f"[{symbol}] stock name lookup failed: {exc}")

        self._stock_name_cache[symbol] = name
        return name

    def _infer_etf_exchange(self, symbol):
        symbol = self._normalize_symbol(symbol)
        return "sz" if symbol.startswith("159") else "sh"

    def _volume_unit_scale_from_source(self, source):
        """把数据源/缓存单位标注解析为"换算到股"的倍数；无法解析时返回 None。"""
        if source is None:
            return None
        key = str(source).strip().upper()
        if not key:
            return None
        key = VOLUME_UNIT_HINT_ALIASES.get(key, key)
        return VOLUME_SOURCE_EXPECTED_SCALE.get(key)

    def _volume_unit_hint_from_frame(self, frame):
        """从缓存帧自带的单位标注列里取出单一标注；缺失/混标时返回 None。

        只读 volume_unit / volume_source 这类"单位语义"列：读取路径会把已经归一化为
        "股"的帧写回磁盘，通用 provenance 列（source/data_source）描述的是数据来源而不是
        盘上存的单位，直接拿来换算会在"已归一化但标注仍是 AKSHARE"时造成二次 ×100。
        """
        if frame is None or not hasattr(frame, "columns") or frame.empty:
            return None
        for column in VOLUME_UNIT_HINT_COLUMNS:
            if column not in frame.columns:
                continue
            values = frame[column].dropna().astype(str).str.strip()
            values = values[~values.str.upper().isin(("", "NAN", "NONE", "UNKNOWN"))]
            unique = pd.unique(values)
            if len(unique) != 1:
                continue
            if self._volume_unit_scale_from_source(unique[0]) is not None:
                return str(unique[0])
        return None

    def _apply_volume_unit_normalization(self, symbol, normalized, source, group_column=None):
        """把 volume 列统一换算为"股"。

        判别优先级（顺序不可颠倒）：

        1. **数据源/缓存单位标注优先**。source 能解析出明确单位时整帧按标注换算，
           amount/(close*volume) 比值只用来记 WARNING，绝不反过来覆盖标注。
        2. 无标注时才启用兜底启发式，且判据必须与复权无关：
           - amount 与 volume 都是不复权口径，故 amount/volume 是**不复权成交均价**。
             它随时间连续（除权跳空至多数倍），只有单位在"股/手"之间切换才会出现
             ~100 倍台阶。据此把帧切成若干"单位一致段"，得到段间的相对单位指数差。
           - 绝对锚点用 amount/(close*volume)：该比值 ≈ qfq 复权因子 × 单位倍数，
             而复权因子恒 >= 1（送转/分红只会摊薄），所以"比值小"是可靠证据、
             "比值大"不是。比值 <= VOLUME_UNIT_SHARE_MAX_RATIO 的行可靠判为"股"，
             再沿段间指数差把结论传播到全帧（qfq 基准日在帧尾，因子恒为 1，
             全历史帧的帧尾必然提供这样的锚点）。
        3. 判不出来时**记 WARNING 并保持原样**，绝不静默 ×100——
           静默的百倍污染比拒绝转换危险得多。

        已修缺陷：旧实现用"比值 >= 10 判手"且优先级高于源标注。因为 amount 不复权、
        close 是 qfq，比值 ≈ 复权因子，凡复权因子 >= 10 的长历史高送转标的都会被
        误判成"手"并 ×100，造成静默的百倍数据污染（直接毒化量比因子与成交量约束）。
        """
        if normalized.empty:
            return normalized
        for column in ("close", "volume", "amount"):
            if column not in normalized.columns:
                return normalized

        close = pd.to_numeric(normalized["close"], errors="coerce")
        volume = pd.to_numeric(normalized["volume"], errors="coerce")
        amount = pd.to_numeric(normalized["amount"], errors="coerce")
        ratio = (amount / (close * volume).replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        ratio_valid = ratio.notna() & (amount > 0) & (volume > 0) & (close > 0)

        expected_scale = self._volume_unit_scale_from_source(source)
        if expected_scale is not None:
            self._warn_volume_unit_tag_conflict(symbol, source, expected_scale, ratio[ratio_valid])
            if float(expected_scale) != 1.0:
                normalized["volume"] = volume * float(expected_scale)
            return normalized

        return self._apply_volume_unit_fallback(
            symbol, normalized, close, volume, amount, ratio, ratio_valid, group_column
        )

    def _warn_volume_unit_tag_conflict(self, symbol, source, expected_scale, observed_ratio):
        """源标注仍然生效，但比值明显指向另一种单位时留下 WARNING（只告警，不覆盖）。"""
        if observed_ratio.empty:
            return
        median_ratio = float(observed_ratio.median())
        if median_ratio <= VOLUME_UNIT_SHARE_MAX_RATIO:
            implied_scale = 1.0
        elif median_ratio >= VOLUME_UNIT_LOT_MIN_RATIO:
            implied_scale = VOLUME_LOT_SIZE
        else:
            implied_scale = None
        if implied_scale is None or implied_scale == float(expected_scale):
            return
        logger.warning(
            f"[{symbol}] 成交量单位校验与数据源 {source} 标注不一致："
            f"标注单位={'手' if float(expected_scale) == VOLUME_LOT_SIZE else '股'}，"
            f"amount/(close*volume) 中位数={median_ratio:.4g} 指向"
            f"{'手' if implied_scale == VOLUME_LOT_SIZE else '股'}；"
            f"以数据源标注为准（比值受 qfq 复权因子干扰，不能反过来覆盖标注），请核查上游数据"
        )

    def _apply_volume_unit_fallback(
        self, symbol, normalized, close, volume, amount, ratio, ratio_valid, group_column
    ):
        """无源标注时的兜底判别（判据与复权无关，判不准就告警且不换算）。"""
        path_valid = amount.notna() & volume.notna() & (amount > 0) & (volume > 0)
        if not path_valid.any():
            return normalized

        # 快路径：全部可判别行的比值都落在"股"的可靠区间 -> 整帧本来就是股，无需换算。
        # 数据湖里绝大多数文件走这条路径，避免为它们付出分段传播的开销。
        if bool((path_valid & ~ratio_valid).sum() == 0) and bool(
            (ratio[ratio_valid] <= VOLUME_UNIT_SHARE_MAX_RATIO).all()
        ):
            return normalized

        if group_column and group_column in normalized.columns:
            groups = normalized[group_column].astype(str)
        else:
            groups = pd.Series("_", index=normalized.index, dtype=object)

        index = normalized.index[path_valid]
        grp = groups.loc[index]
        # 不复权成交均价：amount 与 volume 同为不复权口径，该价格路径完全不受复权影响
        log_price = np.log10((amount.loc[index] / volume.loc[index]).astype(float))
        delta = log_price.diff()
        is_step = grp.eq(grp.shift()) & (
            (delta.abs() - VOLUME_UNIT_STEP_LOG10).abs() <= VOLUME_UNIT_STEP_TOLERANCE
        )
        step = pd.Series(np.where(is_step, np.sign(delta.fillna(0.0)), 0.0), index=index)
        offset = step.groupby(grp, sort=False).cumsum()

        row_ratio = ratio.loc[index]
        judgeable = ratio_valid.loc[index]
        share_like = judgeable & (row_ratio <= VOLUME_UNIT_SHARE_MAX_RATIO)
        lot_like = judgeable & (row_ratio >= VOLUME_UNIT_LOT_MIN_RATIO)

        # base = 让"可靠锚点行"的绝对单位指数落到 0(股)/1(手) 所需的整体平移量
        base = (-offset).where(share_like).groupby(grp, sort=False).median().round()
        # 没有可靠"股"锚点时的低置信度兜底：只有整段中位比值落在"手且复权因子 1~5"的
        # 窄区间才敢猜"手"。深度复权的"股"数据中位比值是 10~40，落不进来 -> 不会被 ×100。
        group_median_ratio = row_ratio.where(judgeable).groupby(grp, sort=False).median()
        guessable = (group_median_ratio >= VOLUME_UNIT_LOT_MIN_RATIO) & (
            group_median_ratio <= VOLUME_UNIT_LOT_MAX_RATIO
        )
        guessed = (1.0 - offset).where(lot_like).groupby(grp, sort=False).median().round()
        guessed = guessed.where(guessable.reindex(guessed.index, fill_value=False))
        low_confidence = base.isna() & guessed.notna()
        base = base.fillna(guessed)

        exponent = offset + grp.map(base)
        resolved = exponent.isin([0.0, 1.0])
        # 单位指数只可能是 0(股) 或 1(手)；出现其它值说明分段传播自相矛盾，按"判不准"处理
        row_scale = pd.Series(1.0, index=index, dtype=float)
        row_scale[resolved & (exponent == 1.0)] = VOLUME_LOT_SIZE

        # 无法判别的行（amount/volume 缺失）随本组已判定行的多数走
        scale = pd.Series(np.nan, index=normalized.index, dtype=float)
        scale.loc[index] = row_scale.where(resolved)
        dominant = exponent.where(resolved).groupby(grp, sort=False).median().round()
        dominant = dominant.where(dominant.isin([0.0, 1.0]))
        fill = groups.map(dominant).map({0.0: 1.0, 1.0: VOLUME_LOT_SIZE})
        scale = scale.fillna(pd.to_numeric(fill, errors="coerce")).fillna(1.0)

        self._log_volume_unit_fallback(
            symbol, grp, ratio, ratio_valid, base, low_confidence, resolved
        )

        if (scale != 1.0).any():
            normalized["volume"] = volume * scale
        return normalized

    def _log_volume_unit_fallback(self, symbol, grp, ratio, ratio_valid, base, low_confidence, resolved):
        """兜底判别的可观测性：判不准 / 低置信度 / 段间矛盾都必须留痕，不允许静默。"""
        def _describe(keys):
            keys = [str(key) for key in keys]
            head = "、".join(keys[:5])
            return head if len(keys) <= 5 else f"{head} 等 {len(keys)} 个"

        median_ratio = float(ratio[ratio_valid].median()) if ratio_valid.any() else float("nan")
        unresolved_groups = base.index[base.isna()].tolist()
        if unresolved_groups:
            logger.warning(
                f"[{symbol}] 成交量单位无法判定（无数据源标注，且帧内找不到 "
                f"amount/(close*volume) <= {VOLUME_UNIT_SHARE_MAX_RATIO:g} 的可靠'股'锚点，"
                f"中位比值={median_ratio:.4g}）：{_describe(unresolved_groups)} 保持原样不换算。"
                f"注意该比值 ≈ qfq 复权因子 × 单位倍数，深度复权标的会把比值抬高，"
                f"此时按比值 ×100 会造成百倍数据污染，故拒绝换算"
            )
        guess_groups = low_confidence.index[low_confidence].tolist()
        if guess_groups:
            logger.warning(
                f"[{symbol}] 成交量单位低置信度判为'手'（无数据源标注，帧内没有可靠'股'锚点，"
                f"仅凭比值 >= {VOLUME_UNIT_LOT_MIN_RATIO:g} 推断，中位比值={median_ratio:.4g}）："
                f"{_describe(guess_groups)} 已按 ×{VOLUME_LOT_SIZE:g} 换算，请补齐数据源标注以消除歧义"
            )
        conflict = int((~resolved).sum())
        if conflict:
            conflict_groups = pd.unique(grp[~resolved]).tolist()
            logger.warning(
                f"[{symbol}] 成交量单位分段传播出现矛盾：{conflict} 行的单位指数不在 0/1 内"
                f"（{_describe(conflict_groups)}），这些行保持原样不换算"
            )

    def _stamp_frame_attrs(self, normalized):
        normalized.attrs["adjust"] = "qfq"
        normalized.attrs["adjust_note"] = ADJUST_NOTE
        normalized.attrs["volume_unit"] = "share"
        return normalized

    def _normalize_market_frame(self, symbol, df, source=None):
        if df is None or df.empty:
            return pd.DataFrame()

        normalized = df.copy().rename(columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_chg",
            "换手率": "turn",
            "turnover_rate": "turnover_rate",
            "振幅": "amplitude",
            "股票代码": "stock_code",
            "基金代码": "stock_code",
            "基金名称": "stock_name",
            "名称": "stock_name",
            "pctChg": "pct_chg",
            "peTTM": "pe",
            "pbMRQ": "pb",
            "psTTM": "ps",
            "pcfNcfTTM": "pcf",
            "isST": "is_st",
        })

        if "date" not in normalized.columns:
            return pd.DataFrame()

        normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
        normalized = normalized.dropna(subset=["date"]).copy()
        if normalized.empty:
            return pd.DataFrame()

        normalized["date"] = normalized["date"].dt.strftime("%Y-%m-%d")

        for column in NORMALIZED_NUMERIC_COLUMNS:
            if column in normalized.columns:
                normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

        is_etf = self.is_etf_symbol(symbol)
        # ST 来源标记：仅 Baostock 提供按日 isST；缺失补 0 时必须让引擎知道 is_st==0 可能是数据缺失
        had_is_st_column = "is_st" in normalized.columns
        had_st_source_column = "st_source" in normalized.columns
        defaults = {
            "open": np.nan,
            "high": np.nan,
            "low": np.nan,
            "close": np.nan,
            "volume": np.nan,
            "amount": np.nan,
            "pct_chg": np.nan,
            "turn": np.nan,
            "turnover_rate": np.nan,
            "tradestatus": "1",
            "pe": 0 if is_etf else np.nan,
            "pb": 0 if is_etf else np.nan,
            "ps": 0 if is_etf else np.nan,
            "pcf": 0 if is_etf else np.nan,
            "amplitude": np.nan,
            "prev_close": np.nan,
            "intraday_ret": np.nan,
            "open_gap": np.nan,
            "is_st": 0,
            "stock_code": symbol,
            "stock_name": PRETTY_NAMES.get(symbol, symbol),
        }
        for column, default in defaults.items():
            if column not in normalized.columns:
                normalized[column] = default

        normalized["stock_code"] = (
            normalized["stock_code"]
            .fillna(symbol)
            .astype(str)
            .str.extract(r"(\d{6})", expand=False)
            .fillna(symbol)
        )
        normalized["stock_name"] = normalized["stock_name"].fillna("").astype(str).str.strip()
        normalized.loc[normalized["stock_name"] == "", "stock_name"] = PRETTY_NAMES.get(symbol, symbol)
        normalized["tradestatus"] = normalized["tradestatus"].fillna("1").astype(str)
        normalized["is_st"] = pd.to_numeric(normalized["is_st"], errors="coerce").fillna(0).astype(int)
        if had_st_source_column:
            normalized["st_source"] = (
                normalized["st_source"].fillna("unknown").astype(str).replace({"": "unknown", "nan": "unknown"})
            )
        elif had_is_st_column:
            # 仅 Baostock 提供真实按日 ST 状态；存量缓存里的 is_st 无法回溯来源，标 unknown
            normalized["st_source"] = "baostock_daily" if source == "BAOSTOCK" else "unknown"
        else:
            normalized["st_source"] = "missing"
        normalized = normalized.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
        normalized = self._apply_volume_unit_normalization(symbol, normalized, source)

        inferred_prev_close = normalized["close"] / (1.0 + normalized["pct_chg"] / 100.0)
        normalized["prev_close"] = normalized["prev_close"].fillna(normalized["close"].shift(1)).fillna(inferred_prev_close)
        normalized["intraday_ret"] = normalized["intraday_ret"].fillna(
            normalized["close"] / normalized["open"].replace(0, np.nan) - 1.0
        )
        normalized["open_gap"] = normalized["open_gap"].fillna(
            normalized["open"] / normalized["prev_close"].replace(0, np.nan) - 1.0
        )
        normalized["amplitude"] = normalized["amplitude"].fillna(
            (normalized["high"] - normalized["low"]) / normalized["prev_close"].replace(0, np.nan) * 100.0
        )
        normalized["amplitude"] = normalized["amplitude"].fillna(
            (normalized["high"] - normalized["low"]) / normalized["close"].replace(0, np.nan) * 100.0
        )
        normalized["turnover_rate"] = normalized["turnover_rate"].fillna(normalized["turn"])
        volume_base = normalized["volume"].rolling(20, min_periods=5).median()
        normalized["turnover_rate"] = normalized["turnover_rate"].fillna(
            normalized["volume"] / volume_base.replace(0, np.nan) * 100.0
        )
        normalized["turn"] = normalized["turn"].fillna(normalized["turnover_rate"])

        base_columns = [
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "pct_chg",
            "turn",
            "turnover_rate",
            "tradestatus",
            "pe",
            "pb",
            "ps",
            "pcf",
            "amplitude",
            "prev_close",
            "intraday_ret",
            "open_gap",
            "is_st",
            "st_source",
            "stock_code",
            "stock_name",
        ]
        extra_columns = [column for column in normalized.columns if column not in base_columns]
        normalized = normalized[base_columns + extra_columns]
        return self._stamp_frame_attrs(normalized)

    def _read_remote_cached_frame(self, symbol):
        import urllib.request
        import json
        import io
        url = f"{self.api_url}/api/v1/market/history?symbol={symbol}"
        cache_key = f"remote_api_{symbol}"
        try:
            with self._frame_cache_lock:
                cached = self._frame_cache.get(cache_key)
                if cached is not None and time.monotonic() - cached[0] < 300:
                    self._frame_cache_touch_locked(cache_key)
                    return cached[1]
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status != 200:
                    return pd.DataFrame()
                data = response.read()
                frame = pd.read_parquet(io.BytesIO(data))
                # 缓存自带单位/来源标注时必须传下去：源标注优先于比值启发式
                frame = self._normalize_market_frame(
                    symbol, frame, source=self._volume_unit_hint_from_frame(frame)
                )

            with self._frame_cache_lock:
                self._frame_cache_store_locked(cache_key, (time.monotonic(), frame))
                start = str(frame["date"].min()) if not frame.empty and "date" in frame.columns else None
                end = str(frame["date"].max()) if not frame.empty and "date" in frame.columns else None
                self._cache_window_cache[cache_key] = (time.monotonic(), start, end)
            return frame
        except Exception as e:
            logger.warning(f"[{symbol}] Remote cache read failed: {e}")
            return pd.DataFrame()

    def _read_cached_frame(self, symbol):
        """读取单标的缓存帧。

        返回的是缓存中的共享帧（不复制）：调用方只允许读取，需要修改时必须自行 copy。
        模块内所有对外出口（get_stock_data 等）均经 _filter_by_range 复制后再返回。
        """
        if self.api_url:
            return self._read_remote_cached_frame(symbol)
        cache_path = self.get_cache_path(symbol)
        if not cache_path.exists():
            return pd.DataFrame()
        try:
            cache_mtime = cache_path.stat().st_mtime
        except OSError:
            return pd.DataFrame()
        cache_key = str(cache_path)
        with self._frame_cache_lock:
            cached = self._frame_cache.get(cache_key)
            if cached is not None and cached[0] == cache_mtime:
                self._frame_cache_touch_locked(cache_key)
                return cached[1]
        try:
            raw_frame = pd.read_parquet(cache_path)
            # 回测主路径：缓存文件若自带单位/来源标注就传下去（源标注优先于比值启发式）。
            # 当前数据湖的存量 parquet 两者皆无，此时走的是与复权无关的兜底判别。
            frame = self._normalize_market_frame(
                symbol, raw_frame, source=self._volume_unit_hint_from_frame(raw_frame)
            )
        except Exception as e:
            logger.warning(f"[{symbol}] Cache read failed: {e}")
            return pd.DataFrame()
        with self._frame_cache_lock:
            self._frame_cache_store_locked(cache_key, (cache_mtime, frame))
            self._cache_window_cache[cache_key] = (
                cache_mtime,
                frame["date"].min() if not frame.empty and "date" in frame.columns else None,
                frame["date"].max() if not frame.empty and "date" in frame.columns else None,
            )
        return frame

    def warm_cached_frames(self, symbols, limit=None):
        warmed = 0
        for symbol in list(symbols)[:limit]:
            if not self._read_cached_frame(symbol).empty:
                warmed += 1
        return warmed

    def get_cached_window(self, symbol):
        symbol = self._normalize_symbol(symbol)
        if getattr(self, "api_url", None):
            cache_key = f"remote_api_{symbol}"
            with self._frame_cache_lock:
                cached_window = self._cache_window_cache.get(cache_key)
                if cached_window is not None and time.monotonic() - cached_window[0] < 300:
                    return cached_window[1], cached_window[2]
            
            import urllib.request
            import json
            url = f"{self.api_url}/api/v1/market/window?symbol={symbol}"
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode('utf-8'))
                        start, end = data.get("start"), data.get("end")
                        with self._frame_cache_lock:
                            self._cache_window_cache[cache_key] = (time.monotonic(), start, end)
                        return start, end
            except Exception as e:
                logger.debug(f"[{symbol}] Remote window read failed: {e}")
            return None, None

        cache_path = self.get_cache_path(symbol)
        if not cache_path.exists():
            return None, None
        cache_key = str(cache_path)
        try:
            cache_mtime = cache_path.stat().st_mtime
        except OSError:
            return None, None

        with self._frame_cache_lock:
            cached_window = self._cache_window_cache.get(cache_key)
            if cached_window is not None and cached_window[0] == cache_mtime:
                return cached_window[1], cached_window[2]

            cached_frame = self._frame_cache.get(cache_key)
            if cached_frame is not None and cached_frame[0] == cache_mtime:
                frame = cached_frame[1]
                if not frame.empty and "date" in frame.columns:
                    start = str(frame["date"].min())
                    end = str(frame["date"].max())
                    self._cache_window_cache[cache_key] = (cache_mtime, start, end)
                    return start, end

        try:
            dates = pd.read_parquet(cache_path, columns=["date"])
        except Exception as exc:
            logger.debug(f"[{symbol}] cache window read failed: {exc}")
            return None, None
        if dates.empty or "date" not in dates.columns:
            return None, None
        date_values = pd.to_datetime(dates["date"], errors="coerce").dropna()
        if date_values.empty:
            return None, None
        start = date_values.min().strftime("%Y-%m-%d")
        end = date_values.max().strftime("%Y-%m-%d")
        with self._frame_cache_lock:
            self._cache_window_cache[cache_key] = (cache_mtime, start, end)
        return start, end

    def _filter_by_range(self, df, start_date, end_date):
        if df.empty:
            return pd.DataFrame()
        return df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy().reset_index(drop=True)

    def _market_trading_calendar(self, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DatetimeIndex:
        if pd.isna(start_ts) or pd.isna(end_ts) or end_ts < start_ts:
            return pd.DatetimeIndex([])

        years = tuple(range(int(start_ts.year), int(end_ts.year) + 1))
        cache_key = ("market_calendar", years)
        with self._frame_cache_lock:
            cached = self._trading_calendar_cache.get(cache_key)
        if cached is not None:
            return cached[(cached >= start_ts) & (cached <= end_ts)]

        consolidated_dir = self.cache_dir / "consolidated"
        dates = []
        for year in years:
            path = consolidated_dir / f"market_{year}.parquet"
            if not path.exists():
                continue
            try:
                frame = pd.read_parquet(path, columns=["date"])
            except Exception:
                try:
                    frame = pd.read_parquet(path, columns=["日期"])
                    frame = frame.rename(columns={"日期": "date"})
                except Exception:
                    continue
            if "date" not in frame.columns:
                continue
            values = pd.to_datetime(frame["date"], errors="coerce").dropna().dt.normalize().drop_duplicates()
            if not values.empty:
                dates.append(values)

        if dates:
            calendar = pd.DatetimeIndex(pd.concat(dates, ignore_index=True).drop_duplicates().sort_values())
        else:
            calendar = pd.DatetimeIndex([])
        with self._frame_cache_lock:
            self._trading_calendar_cache[cache_key] = calendar
        return calendar[(calendar >= start_ts) & (calendar <= end_ts)]

    def _coverage_summary(self, df, start_date, end_date, allow_late_start: bool = False) -> Dict[str, object]:
        filtered = self._filter_by_range(df, start_date, end_date)
        if filtered.empty:
            return {
                "ok": False,
                "observed_days": 0,
                "expected_business_days": 0,
                "coverage_ratio": 0.0,
                "max_consecutive_missing_business_days": 0,
            }

        observed_dates = pd.to_datetime(filtered["date"], errors="coerce").dropna().dt.normalize().drop_duplicates()
        if observed_dates.empty:
            return {
                "ok": False,
                "observed_days": 0,
                "expected_business_days": 0,
                "coverage_ratio": 0.0,
                "max_consecutive_missing_business_days": 0,
            }

        tolerance = pd.Timedelta(days=CACHE_EDGE_TOLERANCE_DAYS)
        start_ts = pd.to_datetime(start_date).normalize()
        end_ts = pd.to_datetime(end_date).normalize()
        start_edge_ok = allow_late_start or observed_dates.min() <= start_ts + tolerance
        end_edge_ok = observed_dates.max() >= end_ts - tolerance
        edge_ok = start_edge_ok and end_edge_ok
        calendar = self._market_trading_calendar(start_ts, end_ts)
        if len(calendar) > 0:
            lower = max(start_ts, observed_dates.min())
            upper = min(end_ts, observed_dates.max())
            expected = calendar[(calendar >= lower) & (calendar <= upper)]
        else:
            expected = pd.bdate_range(start=max(start_ts, observed_dates.min()), end=min(end_ts, observed_dates.max()))
        expected_set = {day.normalize() for day in expected}
        observed_set = {day.normalize() for day in observed_dates}
        missing = sorted(expected_set - observed_set)
        expected_count = len(expected_set)
        coverage_ratio = len(observed_set & expected_set) / expected_count if expected_count else 0.0
        max_gap = 0
        current_gap = 0
        for day in expected:
            if day.normalize() in observed_set:
                current_gap = 0
            else:
                current_gap += 1
                max_gap = max(max_gap, current_gap)
        ok = bool(edge_ok and coverage_ratio >= 0.65 and max_gap <= 5)
        return {
            "ok": ok,
            "observed_days": int(len(observed_set & expected_set)),
            "expected_business_days": int(expected_count),
            "coverage_ratio": float(coverage_ratio),
            "max_consecutive_missing_business_days": int(max_gap),
            "first_observed_date": observed_dates.min().strftime("%Y-%m-%d"),
            "last_observed_date": observed_dates.max().strftime("%Y-%m-%d"),
            "missing_business_days_sample": [day.strftime("%Y-%m-%d") for day in missing[:10]],
        }

    def _has_range_coverage(self, df, start_date, end_date, allow_late_start: bool = False):
        return bool(self._coverage_summary(df, start_date, end_date, allow_late_start=allow_late_start).get("ok"))

    def _normalize_pool_market_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        normalized = df.copy().rename(columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_chg",
            "换手率": "turn",
            "振幅": "amplitude",
            "股票代码": "stock_code",
            "基金代码": "stock_code",
            "基金名称": "stock_name",
            "名称": "stock_name",
            "pctChg": "pct_chg",
            "peTTM": "pe",
            "pbMRQ": "pb",
            "psTTM": "ps",
            "pcfNcfTTM": "pcf",
            "isST": "is_st",
        })

        if "date" not in normalized.columns or "stock_code" not in normalized.columns:
            return pd.DataFrame()

        normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
        normalized = normalized.dropna(subset=["date"]).copy()
        if normalized.empty:
            return pd.DataFrame()
        normalized["date"] = normalized["date"].dt.strftime("%Y-%m-%d")
        normalized["stock_code"] = (
            normalized["stock_code"]
            .astype(str)
            .str.extract(r"(\d{6})", expand=False)
        )
        normalized = normalized.dropna(subset=["stock_code"]).copy()
        if normalized.empty:
            return pd.DataFrame()

        for column in NORMALIZED_NUMERIC_COLUMNS:
            if column in normalized.columns:
                normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

        had_is_st_column = "is_st" in normalized.columns
        had_st_source_column = "st_source" in normalized.columns
        defaults = {
            "stock_name": "",
            "open": np.nan,
            "high": np.nan,
            "low": np.nan,
            "close": np.nan,
            "volume": np.nan,
            "amount": np.nan,
            "pct_chg": np.nan,
            "turn": np.nan,
            "turnover_rate": np.nan,
            "tradestatus": "1",
            "pe": np.nan,
            "pb": np.nan,
            "ps": np.nan,
            "pcf": np.nan,
            "amplitude": np.nan,
            "prev_close": np.nan,
            "intraday_ret": np.nan,
            "open_gap": np.nan,
            "is_st": 0,
        }
        for column, default in defaults.items():
            if column not in normalized.columns:
                normalized[column] = default

        normalized = normalized.sort_values(["stock_code", "date"]).drop_duplicates(
            subset=["stock_code", "date"], keep="last"
        ).reset_index(drop=True)
        normalized["stock_name"] = normalized["stock_name"].fillna("").astype(str).str.strip()
        missing_name_mask = (
            (normalized["stock_name"] == "")
            | (normalized["stock_name"] == normalized["stock_code"])
        )
        if missing_name_mask.any():
            name_map = {
                symbol: self.get_stock_name(symbol)
                for symbol in normalized.loc[missing_name_mask, "stock_code"].dropna().unique().tolist()
            }
            normalized.loc[missing_name_mask, "stock_name"] = (
                normalized.loc[missing_name_mask, "stock_code"].map(name_map).fillna(normalized.loc[missing_name_mask, "stock_code"])
            )
        normalized["tradestatus"] = normalized["tradestatus"].fillna("1").astype(str)
        normalized["is_st"] = pd.to_numeric(normalized["is_st"], errors="coerce").fillna(0).astype(int)
        if had_st_source_column:
            normalized["st_source"] = (
                normalized["st_source"].fillna("unknown").astype(str).replace({"": "unknown", "nan": "unknown"})
            )
        elif had_is_st_column:
            # 合并年度文件来源不可回溯，is_st 可能是真实状态也可能是历史补 0
            normalized["st_source"] = "unknown"
        else:
            normalized["st_source"] = "missing"
        # 池帧是多标的堆叠：单位判别依赖"单标的不复权价路径"，必须按 stock_code 分组
        normalized = self._apply_volume_unit_normalization(
            "POOL", normalized, self._volume_unit_hint_from_frame(normalized), group_column="stock_code"
        )

        grouped = normalized.groupby("stock_code", group_keys=False)
        inferred_prev_close = normalized["close"] / (1.0 + normalized["pct_chg"] / 100.0)
        normalized["prev_close"] = normalized["prev_close"].fillna(grouped["close"].shift(1)).fillna(inferred_prev_close)
        normalized["intraday_ret"] = normalized["intraday_ret"].fillna(
            normalized["close"] / normalized["open"].replace(0, np.nan) - 1.0
        )
        normalized["open_gap"] = normalized["open_gap"].fillna(
            normalized["open"] / normalized["prev_close"].replace(0, np.nan) - 1.0
        )
        normalized["amplitude"] = normalized["amplitude"].fillna(
            (normalized["high"] - normalized["low"]) / normalized["prev_close"].replace(0, np.nan) * 100.0
        )
        normalized["amplitude"] = normalized["amplitude"].fillna(
            (normalized["high"] - normalized["low"]) / normalized["close"].replace(0, np.nan) * 100.0
        )
        normalized["turnover_rate"] = normalized["turnover_rate"].fillna(normalized["turn"])
        normalized["turn"] = normalized["turn"].fillna(normalized["turnover_rate"])
        return self._stamp_frame_attrs(normalized)

    def _dedupe_normalized_symbols(self, symbols) -> List[str]:
        seen = set()
        ordered = []
        for symbol in symbols:
            code = self._normalize_symbol(symbol)
            if not code or code in seen:
                continue
            seen.add(code)
            ordered.append(code)
        return ordered

    def _read_consolidated_pool_data(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        allow_late_start: bool = False,
    ) -> Tuple[pd.DataFrame, Dict[str, str], List[str]]:
        if getattr(self, "api_url", None):
            return pd.DataFrame(), {}, list(symbols)
            
        start_year = int(start_date[:4])
        end_year = int(end_date[:4])
        frames = []
        used_years = []
        consolidated_dir = self.cache_dir / "consolidated"

        for year in range(start_year, end_year + 1):
            consolidated_path = consolidated_dir / f"market_{year}.parquet"
            if not consolidated_path.exists():
                continue
            try:
                year_df = pd.read_parquet(
                    consolidated_path,
                    filters=[("stock_code", "in", symbols)],
                )
            except Exception as exc:
                logger.debug(f"Consolidated filtered read failed for {year}, falling back to full read: {exc}")
                year_df = pd.read_parquet(consolidated_path)

            normalized = self._normalize_pool_market_frame(year_df)
            if normalized.empty:
                continue
            frames.append(normalized[normalized["stock_code"].isin(symbols)].copy())
            used_years.append(year)

        if not frames:
            return pd.DataFrame(), {}, list(symbols)

        combined = self._filter_by_range(pd.concat(frames, ignore_index=True, sort=False), start_date, end_date)
        complete_frames = []
        data_sources = {}
        missing = []
        grouped = combined.groupby("stock_code") if not combined.empty else None

        for symbol in symbols:
            symbol_df = (
                grouped.get_group(symbol).copy()
                if grouped is not None and symbol in grouped.groups
                else pd.DataFrame()
            )
            if self._has_range_coverage(symbol_df, start_date, end_date, allow_late_start=allow_late_start):
                complete_frames.append(symbol_df)
                if len(used_years) == 1:
                    data_sources[symbol] = f"CONSOLIDATED_{used_years[0]}"
                else:
                    data_sources[symbol] = "CONSOLIDATED"
            else:
                missing.append(symbol)

        pool_df = pd.concat(complete_frames, ignore_index=True, sort=False) if complete_frames else pd.DataFrame()
        return pool_df, data_sources, missing

    def _merge_and_save_cache(self, symbol, cached_df, fetched_df):
        merged = pd.concat([cached_df, fetched_df], ignore_index=True, sort=False)
        merged = self._normalize_market_frame(symbol, merged)
        if not merged.empty:
            if getattr(self, "api_url", None):
                cache_key = f"remote_api_{symbol}"
                with self._frame_cache_lock:
                    self._frame_cache_store_locked(cache_key, (time.monotonic(), merged))
                    self._cache_window_cache.pop(cache_key, None)
                return merged

            cache_path = self.get_cache_path(symbol)
            with self._cache_write_locks_lock:
                lock = self._cache_write_locks.setdefault(str(cache_path), threading.Lock())
            with lock:
                tmp_path = cache_path.with_name(f".{cache_path.name}.tmp")
                merged.to_parquet(tmp_path, index=False)
                tmp_path.replace(cache_path)
            with self._frame_cache_lock:
                self._frame_cache.pop(str(cache_path), None)
                self._cache_window_cache.pop(str(cache_path), None)
        return merged

    def _fetch_from_akshare(self, symbol, start_date, end_date):
        ak = _get_akshare()
        symbol = self._normalize_symbol(symbol)
        is_etf = self.is_etf_symbol(symbol)
        fetchers = []

        if is_etf:
            fetchers.extend([
                ("AKSHARE", lambda: ak.fund_etf_hist_em(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    adjust="qfq",
                )),
                ("AKSHARE_SINA", lambda: ak.fund_etf_hist_sina(symbol=f"{self._infer_etf_exchange(symbol)}{symbol}")),
                ("AKSHARE", lambda: ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    adjust="qfq",
                )),
            ])
        else:
            fetchers.append(("AKSHARE", lambda: ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
            )))

        last_error = None
        for source, fetcher in fetchers:
            try:
                with _no_proxy_environment():
                    raw_df = fetcher()
                normalized = self._normalize_market_frame(symbol, raw_df, source=source)
                filtered = self._filter_by_range(normalized, start_date, end_date)
                if not filtered.empty:
                    return filtered, source
            except Exception as e:
                last_error = e

        if last_error is not None:
            logger.warning(f"[{symbol}] AKShare Error: {last_error}")
        return pd.DataFrame(), ""

    def _fetch_from_baostock(self, symbol, start_date, end_date, auto_login=True):
        if not auto_login:
            return pd.DataFrame(), ""

        bs = _get_baostock()
        symbol = self._normalize_symbol(symbol)
        with self._baostock_lock, _no_proxy_environment():
            login_result = bs.login()
            if login_result.error_code != "0":
                logger.warning(f"[{symbol}] Baostock login failed: {login_result.error_msg}")
                return pd.DataFrame(), ""

            try:
                bs_symbol = self._get_bs_symbol(symbol)
                fields = "date,open,high,low,close,volume,amount,pctChg,turn,tradestatus,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
                rs = bs.query_history_k_data_plus(
                    bs_symbol,
                    fields,
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="2",
                )
                data_list = []
                while rs.next():
                    data_list.append(rs.get_row_data())
                if not data_list:
                    return pd.DataFrame(), ""

                new_df = pd.DataFrame(data_list, columns=rs.fields)
                rs_name = bs.query_stock_basic(code=bs_symbol)
                if rs_name.next():
                    stock_name = rs_name.get_row_data()[1]
                else:
                    stock_name = PRETTY_NAMES.get(symbol, symbol)
                new_df["stock_code"] = symbol
                new_df["stock_name"] = stock_name
                normalized = self._normalize_market_frame(symbol, new_df, source="BAOSTOCK")
                return self._filter_by_range(normalized, start_date, end_date), "BAOSTOCK"
            except Exception as e:
                logger.warning(f"[{symbol}] Baostock Error: {e}")
                return pd.DataFrame(), ""
            finally:
                bs.logout()

    def list_local_codes(self, asset_type="a_share"):
        now = time.monotonic()
        cached = self._local_codes_cache.get(asset_type)
        cached_ts = self._local_codes_cache_ts.get(asset_type, 0.0)
        if cached is not None and now - cached_ts < 60:
            return list(cached)

        search_dir = self.etf_cache_dir if asset_type == "etf" else self.cache_dir
        codes = sorted(
            entry.name.split("_")[0]
            for entry in os.scandir(search_dir)
            if entry.is_file() and entry.name.endswith("_full_history.parquet")
        )
        self._local_codes_cache[asset_type] = codes
        self._local_codes_cache_ts[asset_type] = now
        return list(codes)

    def get_local_code_count(self, asset_type="a_share"):
        return len(self.list_local_codes(asset_type))

    def select_local_a_share_symbols(
        self,
        limit: int,
        min_end_date: Optional[str] = None,
        min_start_date: Optional[str] = None,
        allow_late_start: bool = False,
    ) -> List[str]:
        limit = int(limit or 0)
        if limit <= 0:
            return []

        cache_key = ("a_share_research_sample_v2", limit, min_end_date or "", min_start_date or "", bool(allow_late_start))
        now = time.monotonic()
        cached = self._symbol_selection_cache.get(cache_key)
        if cached is not None and now - cached[0] < 300:
            self._last_symbol_selection_metadata = dict(cached[2] if len(cached) > 2 else {})
            return list(cached[1])

        candidate_limit = max(limit * 12, limit + 500)
        symbols, metadata = self._select_research_sample_from_consolidated(
            limit,
            candidate_limit,
            min_end_date,
            min_start_date,
            allow_late_start=allow_late_start,
        )
        if len(symbols) < limit:
            metadata.setdefault("fallback_used", True)
            fallback = self._select_liquid_symbols_from_latest_rows(candidate_limit, min_end_date)
            seen = set(symbols)
            for symbol in fallback:
                if symbol in seen:
                    continue
                if not self._symbol_cache_window_covers(symbol, min_start_date, min_end_date, allow_late_start=allow_late_start):
                    continue
                symbols.append(symbol)
                seen.add(symbol)
                if len(symbols) >= limit:
                    break

        symbols = symbols[:limit]
        metadata.update(
            {
                "requested_limit": limit,
                "selected_symbols": len(symbols),
                "min_end_date": min_end_date,
                "min_start_date": min_start_date,
                "allow_late_start": bool(allow_late_start),
            }
        )
        self._last_symbol_selection_metadata = metadata
        self._symbol_selection_cache[cache_key] = (now, symbols, metadata)
        return list(symbols)

    def get_last_symbol_selection_metadata(self) -> Dict[str, object]:
        return dict(self._last_symbol_selection_metadata or {})

    def _filter_symbols_by_cache_window(
        self,
        symbols: List[str],
        limit: int,
        min_start_date: Optional[str],
        min_end_date: Optional[str],
        allow_late_start: bool = False,
    ) -> List[str]:
        selected = []
        for symbol in symbols:
            if not self._symbol_cache_window_covers(symbol, min_start_date, min_end_date, allow_late_start=allow_late_start):
                continue
            selected.append(symbol)
            if len(selected) >= limit:
                break
        return selected

    def _symbol_cache_window_covers(
        self,
        symbol: str,
        min_start_date: Optional[str],
        min_end_date: Optional[str],
        allow_late_start: bool = False,
    ) -> bool:
        cache_start, cache_end = self.get_cached_window(symbol)
        if not cache_start or not cache_end:
            return False
        start_dt = pd.to_datetime(cache_start, errors="coerce")
        end_dt = pd.to_datetime(cache_end, errors="coerce")
        if pd.isna(start_dt) or pd.isna(end_dt):
            return False
        requested_start = pd.to_datetime(min_start_date, errors="coerce") if min_start_date else None
        requested_end = pd.to_datetime(min_end_date, errors="coerce") if min_end_date else None
        if requested_start is not None and pd.notna(requested_start):
            tolerance = pd.Timedelta(days=CACHE_EDGE_TOLERANCE_DAYS)
            if not allow_late_start and start_dt > requested_start + tolerance:
                return False
        if requested_end is not None and pd.notna(requested_end):
            tolerance = pd.Timedelta(days=CACHE_EDGE_TOLERANCE_DAYS)
            if end_dt < requested_end - tolerance:
                return False
        return True

    def _select_liquid_symbols_from_consolidated(self, limit: int, min_end_date: Optional[str]) -> List[str]:
        consolidated_dir = self.cache_dir / "consolidated"
        if not consolidated_dir.exists():
            return []
        paths = sorted(consolidated_dir.glob("market_*.parquet"), reverse=True)
        if not paths:
            return []

        min_dt = pd.to_datetime(min_end_date, errors="coerce") if min_end_date else None
        for path in paths[:2]:
            try:
                import pyarrow.parquet as pq

                available = set(pq.read_schema(path).names)
                columns = [column for column in ["date", "stock_code", "close", "amount", "volume", "turnover_rate"] if column in available]
                if "date" not in columns or "stock_code" not in columns:
                    continue
                frame = pd.read_parquet(path, columns=columns)
            except Exception as exc:
                logger.debug(f"Consolidated liquidity selection failed for {path}: {exc}")
                continue

            if frame.empty:
                continue
            frame = frame.copy()
            frame["stock_code"] = frame["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False)
            frame = frame.dropna(subset=["stock_code"])
            frame = frame[~frame["stock_code"].map(self.is_etf_symbol)].copy()
            frame["date_dt"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.dropna(subset=["date_dt"])
            if min_dt is not None and pd.notna(min_dt):
                frame = frame[frame["date_dt"] >= min_dt]
            if frame.empty:
                continue
            for column in ["close", "amount", "volume", "turnover_rate"]:
                if column in frame.columns:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce")
            latest = frame.sort_values(["stock_code", "date_dt"]).groupby("stock_code", as_index=False).tail(1)
            if latest.empty:
                continue
            liquidity = latest.get("amount", pd.Series(index=latest.index, dtype=float)).fillna(0.0)
            if "volume" in latest.columns and "close" in latest.columns:
                liquidity = liquidity.mask(liquidity <= 0, latest["volume"].fillna(0.0) * latest["close"].fillna(0.0))
            latest["liquidity"] = liquidity
            close_filter = latest["close"].fillna(1) > 0 if "close" in latest.columns else pd.Series(True, index=latest.index)
            latest = latest[(latest["liquidity"] > 0) & close_filter].copy()
            if latest.empty:
                continue
            latest = latest.sort_values(["date_dt", "liquidity", "stock_code"], ascending=[False, False, True])
            return latest["stock_code"].head(limit).tolist()
        return []

    def _select_research_sample_from_consolidated(
        self,
        limit: int,
        candidate_limit: int,
        min_end_date: Optional[str],
        min_start_date: Optional[str],
        allow_late_start: bool = False,
    ) -> Tuple[List[str], Dict[str, object]]:
        consolidated_dir = self.cache_dir / "consolidated"
        if not consolidated_dir.exists():
            return [], {"selection_method": "fallback_latest_rows", "fallback_reason": "missing_consolidated_dir"}

        paths = sorted(consolidated_dir.glob("market_*.parquet"), reverse=True)
        if not paths:
            return [], {"selection_method": "fallback_latest_rows", "fallback_reason": "missing_consolidated_files"}

        min_dt = pd.to_datetime(min_end_date, errors="coerce") if min_end_date else None
        frames = []
        used_files = []
        for path in paths[:2]:
            try:
                import pyarrow.parquet as pq

                available = set(pq.read_schema(path).names)
                columns = [column for column in ["date", "stock_code", "close", "amount", "volume", "turnover_rate"] if column in available]
                if "date" not in columns or "stock_code" not in columns or "close" not in columns:
                    continue
                frame = pd.read_parquet(path, columns=columns)
            except Exception as exc:
                logger.debug(f"Consolidated research sample selection failed for {path}: {exc}")
                continue

            if frame.empty:
                continue
            frame = frame.copy()
            frame["stock_code"] = frame["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False)
            frame = frame.dropna(subset=["stock_code"])
            frame = frame[~frame["stock_code"].map(self.is_etf_symbol)].copy()
            frame["date_dt"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.dropna(subset=["date_dt"])
            if frame.empty:
                continue
            for column in ["close", "amount", "volume", "turnover_rate"]:
                if column in frame.columns:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce")
            frames.append(frame)
            used_files.append(path.name)

        if not frames:
            return [], {"selection_method": "fallback_latest_rows", "fallback_reason": "empty_consolidated_frames"}

        frame = pd.concat(frames, ignore_index=True, sort=False)
        frame = frame.sort_values(["stock_code", "date_dt"]).drop_duplicates(["stock_code", "date_dt"], keep="last")
        latest = frame.groupby("stock_code", as_index=False).tail(1).copy()
        if min_dt is not None and pd.notna(min_dt):
            latest = latest[latest["date_dt"] >= min_dt].copy()
        latest = latest[pd.to_numeric(latest["close"], errors="coerce") > 0].copy()
        if latest.empty:
            return [], {"selection_method": "fallback_latest_rows", "fallback_reason": "no_recent_liquid_rows"}

        liquidity = latest.get("amount", pd.Series(index=latest.index, dtype=float)).fillna(0.0)
        if "volume" in latest.columns:
            liquidity = liquidity.mask(liquidity <= 0, latest["volume"].fillna(0.0) * latest["close"].fillna(0.0))
        latest["liquidity"] = liquidity
        latest = latest[(latest["liquidity"] > 0) & latest["liquidity"].replace([np.inf, -np.inf], np.nan).notna()].copy()
        latest = latest.sort_values(["date_dt", "liquidity", "stock_code"], ascending=[False, False, True]).head(candidate_limit)
        if latest.empty:
            return [], {"selection_method": "fallback_latest_rows", "fallback_reason": "no_positive_liquidity"}

        candidate_codes = latest["stock_code"].tolist()
        recent = frame[frame["stock_code"].isin(candidate_codes)].copy()
        if min_dt is not None and pd.notna(min_dt):
            recent_start = min_dt - pd.Timedelta(days=140)
            recent = recent[recent["date_dt"] >= recent_start].copy()
        recent = recent.sort_values(["stock_code", "date_dt"])

        rows = []
        for symbol, group in recent.groupby("stock_code", sort=False):
            latest_row = latest[latest["stock_code"] == symbol]
            if latest_row.empty:
                continue
            if not self._symbol_cache_window_covers(symbol, min_start_date, min_end_date, allow_late_start=allow_late_start):
                continue
            group = group.dropna(subset=["close"]).copy()
            if len(group) < 20:
                continue
            close = pd.to_numeric(group["close"], errors="coerce")
            returns = close.pct_change()
            amount = pd.to_numeric(group.get("amount", pd.Series(index=group.index)), errors="coerce")
            volume = pd.to_numeric(group.get("volume", pd.Series(index=group.index)), errors="coerce")
            liquidity_series = amount.fillna(0.0)
            liquidity_series = liquidity_series.mask(liquidity_series <= 0, volume.fillna(0.0) * close.fillna(0.0))
            rows.append(
                {
                    "stock_code": symbol,
                    "latest_date": latest_row.iloc[0]["date_dt"],
                    "latest_liquidity": float(latest_row.iloc[0]["liquidity"]),
                    "median_liquidity_20d": float(liquidity_series.tail(20).median(skipna=True) or 0.0),
                    "coverage_days": int(group["date_dt"].nunique()),
                    "mom_20d": float(close.iloc[-1] / close.iloc[-21] - 1.0) if len(close.dropna()) >= 21 and close.iloc[-21] else 0.0,
                    "volatility_20d": float(returns.tail(20).std(skipna=True) or 0.0),
                    "turnover_latest": float(pd.to_numeric(latest_row.iloc[0].get("turnover_rate"), errors="coerce") or 0.0),
                }
            )

        metrics = pd.DataFrame(rows)
        if metrics.empty:
            return [], {
                "selection_method": "fallback_latest_rows",
                "fallback_reason": "no_cache_covered_research_candidates",
                "source_files": used_files,
                "prescreen_candidates": int(len(candidate_codes)),
            }

        metrics = metrics.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        metrics["liquidity_rank"] = metrics["median_liquidity_20d"].rank(pct=True, ascending=True)
        metrics["coverage_rank"] = metrics["coverage_days"].rank(pct=True, ascending=True)
        metrics["style_strength"] = metrics["mom_20d"].abs().rank(pct=True, ascending=True)
        metrics["volatility_rank"] = metrics["volatility_20d"].rank(pct=True, ascending=True)
        metrics["research_score"] = (
            metrics["liquidity_rank"] * 0.50
            + metrics["coverage_rank"] * 0.20
            + metrics["style_strength"] * 0.15
            + (1.0 - (metrics["volatility_rank"] - 0.55).abs()).clip(lower=0.0) * 0.10
            + metrics["turnover_latest"].rank(pct=True, ascending=True).fillna(0.0) * 0.05
        )

        try:
            metrics["liquidity_tier"] = pd.qcut(
                metrics["median_liquidity_20d"].rank(method="first"),
                q=min(4, max(1, len(metrics) // max(1, limit // 6))),
                labels=False,
                duplicates="drop",
            ).fillna(0).astype(int)
        except ValueError:
            metrics["liquidity_tier"] = 0
        try:
            momentum_bucket = pd.qcut(metrics["mom_20d"].rank(method="first"), q=3, labels=False, duplicates="drop")
            volatility_bucket = pd.qcut(metrics["volatility_20d"].rank(method="first"), q=3, labels=False, duplicates="drop")
            metrics["style_bucket"] = momentum_bucket.fillna(0).astype(int).astype(str) + "_" + volatility_bucket.fillna(0).astype(int).astype(str)
        except ValueError:
            metrics["style_bucket"] = "0_0"

        selected = []
        selected_set = set()
        grouped = {
            key: group.sort_values("research_score", ascending=False)["stock_code"].tolist()
            for key, group in metrics.groupby(["liquidity_tier", "style_bucket"], sort=False)
        }
        ordered_keys = sorted(
            grouped.keys(),
            key=lambda key: metrics[
                (metrics["liquidity_tier"] == key[0]) & (metrics["style_bucket"] == key[1])
            ]["research_score"].mean(),
            reverse=True,
        )
        cursor = {key: 0 for key in ordered_keys}
        while len(selected) < limit and ordered_keys:
            progressed = False
            for key in ordered_keys:
                bucket = grouped[key]
                idx = cursor[key]
                while idx < len(bucket) and bucket[idx] in selected_set:
                    idx += 1
                cursor[key] = idx + 1
                if idx >= len(bucket):
                    continue
                selected.append(bucket[idx])
                selected_set.add(bucket[idx])
                progressed = True
                if len(selected) >= limit:
                    break
            if not progressed:
                break

        if len(selected) < limit:
            tail = metrics.sort_values("research_score", ascending=False)["stock_code"].tolist()
            for symbol in tail:
                if symbol in selected_set:
                    continue
                selected.append(symbol)
                selected_set.add(symbol)
                if len(selected) >= limit:
                    break

        tier_counts = metrics[metrics["stock_code"].isin(selected)]["liquidity_tier"].value_counts().sort_index().to_dict()
        style_counts = metrics[metrics["stock_code"].isin(selected)]["style_bucket"].value_counts().sort_index().to_dict()
        metadata = {
            "selection_method": "full_market_research_prescreen_v2",
            "method_cn": "全市场研究样本：先保流动性和历史覆盖，再按动量/波动风格分层抽样",
            "source_files": used_files,
            "prescreen_candidates": int(len(candidate_codes)),
            "cache_covered_candidates": int(len(metrics)),
            "liquidity_tier_counts": {str(key): int(value) for key, value in tier_counts.items()},
            "style_bucket_counts": {str(key): int(value) for key, value in style_counts.items()},
            "median_liquidity_20d": float(metrics[metrics["stock_code"].isin(selected)]["median_liquidity_20d"].median() or 0.0),
            "sample_refresh_rule": "同一数据湖、同一日期窗口和同一样本上限下结果稳定；数据更新后会重新计算流动性、动量/波动分层和候选因子。",
        }
        return selected[:limit], metadata

    def _select_liquid_symbols_from_latest_rows(self, limit: int, min_end_date: Optional[str]) -> List[str]:
        import concurrent.futures

        min_dt = pd.to_datetime(min_end_date, errors="coerce") if min_end_date else None
        source_symbols = [symbol for symbol in self.list_local_codes("a_share") if not self.is_etf_symbol(symbol)]

        def latest_row(symbol):
            row = self._read_latest_cached_row(symbol)
            if row is None:
                return None
            row_date = pd.to_datetime(row.get("日期"), errors="coerce")
            if min_dt is not None and pd.notna(min_dt) and (pd.isna(row_date) or row_date < min_dt):
                return None
            amount = row.get("成交额") or 0.0
            volume = row.get("成交量") or 0.0
            close = row.get("最新价") or 0.0
            liquidity = float(amount or 0.0)
            if liquidity <= 0:
                liquidity = float(volume or 0.0) * float(close or 0.0)
            if liquidity <= 0 or not np.isfinite(liquidity):
                return None
            safe_date = row_date if pd.notna(row_date) else pd.Timestamp.min
            return {
                "symbol": symbol,
                "date": safe_date,
                "liquidity": liquidity,
            }

        rows = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            for row in executor.map(latest_row, source_symbols):
                if row is not None:
                    rows.append(row)
        rows.sort(key=lambda item: (item["date"], item["liquidity"], item["symbol"]), reverse=True)
        return [row["symbol"] for row in rows[:limit]]

    def _read_latest_cached_row(self, symbol):
        symbol = self._normalize_symbol(symbol)
        cache_path = self.get_cache_path(symbol)
        if not cache_path.exists():
            return None

        columns = [
            "date",
            "stock_code",
            "stock_name",
            "close",
            "pct_chg",
            "volume",
            "amount",
            "turn",
            "turnover_rate",
        ]
        try:
            import pyarrow.parquet as pq

            available_columns = set(pq.read_schema(cache_path).names)
            read_columns = [column for column in columns if column in available_columns and column != "stock_code"]
            if "date" not in read_columns:
                return None
            frame = pd.read_parquet(cache_path, columns=read_columns)
        except Exception as exc:
            logger.debug(f"[{symbol}] latest cache row read failed: {exc}")
            return None

        if frame.empty or "date" not in frame.columns:
            return None

        row = frame.sort_values("date").tail(1).iloc[0]
        def finite_float(value, default=None):
            try:
                number = float(value)
            except Exception:
                return default
            return number if np.isfinite(number) else default

        pct_chg = finite_float(row.get("pct_chg", 0), 0.0)
        close = finite_float(row.get("close", None), None)

        return {
            "代码": symbol,
            "名称": str(row.get("stock_name") or PRETTY_NAMES.get(symbol, symbol)),
            "最新价": close,
            "涨跌幅": pct_chg,
            "成交量": finite_float(row.get("volume", 0), 0.0),
            "成交额": finite_float(row.get("amount", 0), 0.0),
            "换手率": finite_float(row.get("turnover_rate", row.get("turn", 0)), 0.0),
            "日期": str(row.get("date", "")),
            "source": "LOCAL_CACHE",
        }

    def _generate_mock_data(self, symbol, start_date, end_date):
        """
        Generate realistic mock data if all else fails.
        """
        dates = pd.date_range(start_date, end_date)
        df = pd.DataFrame({'date': [d.strftime('%Y-%m-%d') for d in dates]})
        df['dt'] = pd.to_datetime(df['date'])
        df = df[df['dt'].dt.dayofweek < 5].copy()
        
        np.random.seed(hash(symbol) % 4294967295)
        price = 100.0 if symbol.startswith('6') else 10.0
        if symbol.startswith('5') or symbol.startswith('1'): price = 3.0 # ETF
        
        close_prices = []
        curr = price
        for _ in range(len(df)):
            change = np.random.normal(0.0002, 0.012) # Slight drift
            curr *= (1 + change)
            close_prices.append(curr)
        
        df['close'] = close_prices
        df['open'] = df['close'] * (1 + np.random.normal(0, 0.003, len(df)))
        df['high'] = df[['open', 'close']].max(axis=1) * (1 + np.abs(np.random.normal(0, 0.005, len(df))))
        df['low'] = df[['open', 'close']].min(axis=1) * (1 - np.abs(np.random.normal(0, 0.005, len(df))))
        df['volume'] = np.random.randint(100000, 1000000, len(df))
        df['amount'] = df['volume'] * df['close']
        df['pct_chg'] = df['close'].pct_change().fillna(0) * 100
        is_etf = self.is_etf_symbol(symbol)
        df['pe'] = 15.0 if not is_etf else 0
        df['pb'] = 2.0 if not is_etf else 0
        df['stock_code'] = symbol
        df['stock_name'] = PRETTY_NAMES.get(symbol, f"模拟_{symbol}")

        return self._normalize_market_frame(symbol, df.drop(columns=['dt']), source="MOCK")

    def get_stock_data(self, symbol, start_date, end_date, auto_login=True, allow_mock=False, allow_late_start: bool = False):
        """
        Fetch historical daily K-line with multiple fallbacks.
        Returns: (df, data_source)
        """
        symbol = self._normalize_symbol(symbol)
        cached = self._read_cached_frame(symbol)
        cache_start = cached["date"].min() if not cached.empty else None
        cache_end = cached["date"].max() if not cached.empty else None
        if self._has_range_coverage(cached, start_date, end_date, allow_late_start=allow_late_start):
            logger.info(f"[{symbol}] Data loaded from CACHE")
            return self._filter_by_range(cached, start_date, end_date), "CACHE"

        if not cached.empty:
            cache_start = cached["date"].min()
            cache_end = cached["date"].max()
            logger.info(f"[{symbol}] Cache coverage gap detected: have {cache_start} -> {cache_end}, need {start_date} -> {end_date}")

        fetched_df, source = self._fetch_from_akshare(symbol, start_date, end_date)
        merged = cached
        if not fetched_df.empty:
            merged = self._merge_and_save_cache(symbol, cached, fetched_df)
            if self._has_range_coverage(merged, start_date, end_date, allow_late_start=allow_late_start):
                logger.info(f"[{symbol}] Data backfilled from {source}")
                source_label = source if cached.empty else f"CACHE+{source}"
                return self._filter_by_range(merged, start_date, end_date), source_label

        fetched_df, source = self._fetch_from_baostock(symbol, start_date, end_date, auto_login=auto_login)
        if not fetched_df.empty:
            merged = self._merge_and_save_cache(symbol, merged, fetched_df)
            if self._has_range_coverage(merged, start_date, end_date, allow_late_start=allow_late_start):
                logger.info(f"[{symbol}] Data backfilled from {source}")
                source_label = source if cached.empty and merged.equals(fetched_df) else f"CACHE+{source}"
                return self._filter_by_range(merged, start_date, end_date), source_label

        if not allow_mock:
            raise DataFetchError(
                symbol,
                start_date,
                end_date,
                cache_start=str(cache_start) if cache_start is not None else None,
                cache_end=str(cache_end) if cache_end is not None else None,
                attempted_sources=["CACHE", "AKSHARE", "BAOSTOCK"],
            )

        # 3. Mock
        logger.error(f"[{symbol}] Data fetching failed from all sources. Generating MOCK data.")
        return self._generate_mock_data(symbol, start_date, end_date), "MOCK"

    def get_stock_pool_data(self, symbols, start_date, end_date, allow_mock=False, allow_late_start: bool = False):
        """
        Fetch historical data for a list of stocks concurrently.
        Optimized Path: Use consolidated yearly files if requesting many symbols.
        """
        symbols = self._dedupe_normalized_symbols(symbols)
        if not symbols:
            return pd.DataFrame(), {}

        all_data = []
        data_sources = {}
        symbols_to_fetch = list(symbols)

        # --- FAST PATH: Consolidated Yearly Files ---
        try:
            if len(symbols) > 50:
                pool_df, consolidated_sources, missing_symbols = self._read_consolidated_pool_data(
                    symbols,
                    start_date,
                    end_date,
                    allow_late_start=allow_late_start,
                )
                if not pool_df.empty:
                    logger.info(
                        "Using CONSOLIDATED fast path for %s/%s symbols from %s to %s",
                        len(consolidated_sources),
                        len(symbols),
                        start_date,
                        end_date,
                    )
                    all_data.append(pool_df)
                    data_sources.update(consolidated_sources)
                    symbols_to_fetch = missing_symbols
        except Exception as e:
            logger.warning(f"Consolidated fast path failed, falling back to parallel reads: {e}")
            all_data = []
            data_sources = {}
            symbols_to_fetch = list(symbols)

        if not symbols_to_fetch:
            combined_df = pd.concat(all_data, ignore_index=True, sort=False) if all_data else pd.DataFrame()
            self._last_pool_quality = self._build_pool_quality(
                combined_df,
                symbols,
                start_date,
                end_date,
                data_sources,
                allow_late_start=allow_late_start,
            )
            return combined_df, data_sources

        # --- SLOW PATH: Parallel Individual Reads ---
        import concurrent.futures

        failures = {}
        
        def fetch(symbol):
            return self.get_stock_data(
                symbol,
                start_date,
                end_date,
                auto_login=True,
                allow_mock=allow_mock,
                allow_late_start=allow_late_start,
            )
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_symbol = {executor.submit(fetch, sym): sym for sym in symbols_to_fetch}
            for future in concurrent.futures.as_completed(future_to_symbol):
                sym = future_to_symbol[future]
                try:
                    df, source = future.result()
                    if not df.empty:
                        all_data.append(df)
                        data_sources[sym] = source
                except DataFetchError as e:
                    logger.error(f"[{sym}] Real data load failed: {e}")
                    failures[sym] = str(e)
                except Exception as e:
                    logger.error(f"[{sym}] Thread failed: {e}")
                    failures[sym] = str(e)
                    
        if failures and not allow_mock:
            raise PoolDataFetchError(failures, start_date, end_date)

        combined_df = pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()
        self._last_pool_quality = self._build_pool_quality(
            combined_df,
            symbols,
            start_date,
            end_date,
            data_sources,
            allow_late_start=allow_late_start,
        )
        return combined_df, data_sources

    def _build_pool_quality(
        self,
        df: pd.DataFrame,
        symbols,
        start_date,
        end_date,
        data_sources: Dict[str, str],
        allow_late_start: bool = False,
    ) -> Dict[str, object]:
        if df is None or df.empty:
            return {
                "symbols_requested": len(symbols),
                "symbols_loaded": 0,
                "symbols_with_sparse_coverage": len(symbols),
                "sparse_symbols_sample": list(symbols)[:10],
            }
        summaries = {}
        sparse = []
        grouped = df.groupby("stock_code", sort=False)
        for symbol in symbols:
            symbol_df = grouped.get_group(symbol) if symbol in grouped.groups else pd.DataFrame()
            summary = self._coverage_summary(symbol_df, start_date, end_date, allow_late_start=allow_late_start)
            summaries[symbol] = summary
            if not summary.get("ok"):
                sparse.append(symbol)
        return {
            "symbols_requested": len(symbols),
            "symbols_loaded": int(df["stock_code"].nunique()) if "stock_code" in df.columns else 0,
            "symbols_with_sparse_coverage": len(sparse),
            "sparse_symbols_sample": sparse[:10],
            "source_counts": pd.Series(list(data_sources.values())).value_counts().to_dict() if data_sources else {},
            "coverage_by_symbol": summaries,
        }

    def get_last_pool_quality(self) -> Dict[str, object]:
        return dict(self._last_pool_quality)

    def get_csi300_stocks(self):
        return ["000001", "000002", "600000", "600036", "600519"]

    def get_latest_market_overview(self, symbols=None, limit=10):
        cached = self.get_latest_market_cached()
        if cached is not None:
            return cached

        if symbols:
            rows = []
            for symbol in symbols:
                latest = self._read_latest_cached_row(symbol)
                if latest is not None:
                    rows.append(latest)
            if rows:
                rows.sort(key=lambda item: item.get("涨跌幅", 0), reverse=True)
                self._latest_market_cache = rows[:limit]
                self._latest_market_cache_ts = time.monotonic()
                return list(self._latest_market_cache)
            fallback = self.get_latest_market_fallback(symbols, limit)
            self._latest_market_cache = fallback
            self._latest_market_cache_ts = time.monotonic()
            return list(fallback)

        try:
            now = time.monotonic()
            ak = _get_akshare()
            with _no_proxy_environment():
                df = ak.stock_zh_a_spot_em()
            result = df.nlargest(limit, '涨跌幅').to_dict(orient='records')
            self._latest_market_cache = result
            self._latest_market_cache_ts = now
            return list(result)
        except Exception:
            fallback = self.get_latest_market_fallback(symbols, limit)
            self._latest_market_cache = fallback
            self._latest_market_cache_ts = time.monotonic()
            return list(fallback)

    def get_latest_market_cached(self):
        now = time.monotonic()
        if self._latest_market_cache is not None and now - self._latest_market_cache_ts < LATEST_MARKET_CACHE_TTL_SECONDS:
            return list(self._latest_market_cache)
        return None

    def get_latest_market_fallback(self, symbols=None, limit=10):
        source_symbols = symbols or list(PRETTY_NAMES.keys())
        rows = []
        for symbol in source_symbols[:limit]:
            symbol = self._normalize_symbol(symbol)
            rows.append({
                "代码": symbol,
                "名称": PRETTY_NAMES.get(symbol, symbol),
                "最新价": None,
                "涨跌幅": 0.0,
                "成交量": 0.0,
                "成交额": 0.0,
                "换手率": 0.0,
                "日期": "",
                "source": "WARMING_CACHE",
            })
        return rows

    def get_last_trading_day(self) -> str:
        """
        获取当前日期之前的最新交易日 (A股)。
        """
        now = datetime.now()
        # 如果是交易日且已经过 16:00，则最新交易日就是今天
        if now.weekday() < 5:
             if now.hour >= 16:
                 return now.strftime("%Y-%m-%d")
        
        # 否则寻找最近的一个周五或周一至周五
        curr = now - timedelta(days=1)
        while curr.weekday() >= 5: # 5=Sat, 6=Sun
            curr -= timedelta(days=1)
        return curr.strftime("%Y-%m-%d")

    def check_data_integrity(self, symbols: list[str], target_date: str) -> tuple[bool, str]:
        """
        检查指定标的是否已更新到目标日期。
        """
        logger.info(f"正在全量审计 {len(symbols)} 只标的数据完整性 (目标日期: {target_date})...")
        missing = []
        
        # 为了速度，我们并行检查
        import concurrent.futures
        def check_one(sym):
            cache_path = self.get_cache_path(sym)
            if not cache_path.exists(): return sym
            try:
                # 只读取最后一行
                df = pd.read_parquet(cache_path, columns=['date'])
                if target_date not in df['date'].values:
                    return sym
            except:
                return sym
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(check_one, symbols))
            missing = [r for r in results if r is not None]
        
        ready_pct = (len(symbols) - len(missing)) / len(symbols) * 100
        if len(missing) > 0:
            logger.warning(f"全量审计报告: 就绪率 {ready_pct:.1f}%, 缺失 {len(missing)} 只标的。")
            return False, f"数据未完全就绪 ({ready_pct:.1f}%)，缺失 {len(missing)} 只标的。"
        
        return True, "全量数据已就绪"
