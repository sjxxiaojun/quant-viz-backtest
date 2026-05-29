"""
每日晨报生成脚本
- 读取最新因子评分
- 筛选signal=1的股票
- 结合虚拟交易持仓
- 获取实时价格和涨跌幅
- 生成Markdown报告 + JSON输出
"""

import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "results" / "daily-reports"
FACTOR_LAB_SCORES = PROJECT_ROOT / "results" / "quant-factor-mining" / "reports" / "factor_lab" / "latest_scores.csv"
FACTOR_LAB_SUMMARY = PROJECT_ROOT / "results" / "quant-factor-mining" / "reports" / "factor_lab" / "latest_summary.json"
VIRTUAL_TRADING_DB = Path(__file__).resolve().parent / "virtual_trading.db"

# 晨报保留天数
MAX_REPORT_AGE_DAYS = 30

# 模块级共享的 DataManager 实例，避免重复创建
_DM_INSTANCE = None

logger = logging.getLogger("DailyMorningReport")


def _get_dm_instance():
    global _DM_INSTANCE
    if _DM_INSTANCE is None:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from data_manager import DataManager
            _DM_INSTANCE = DataManager()
        except Exception as e:
            logger.warning(f"初始化 DataManager 失败: {e}")
    return _DM_INSTANCE


def get_stock_name_local(stock_code: str) -> str:
    """从本地获取股票名称（零依赖外部API，按需懒加载）"""
    code = str(stock_code).zfill(6)
    
    # 优先使用 DataManager 的单只股票查询（DataManager内部本身自带内存缓存）
    dm = _get_dm_instance()
    if dm is not None:
        try:
            name = dm.get_stock_name(code)
            if name and name != code:
                return name
        except Exception as e:
            logger.warning(f"通过 DataManager 查询股票名称失败 [{code}]: {e}")

    # 兜底：尝试从 scores CSV 取
    try:
        df = pd.read_csv(FACTOR_LAB_SCORES, usecols=["stock_code", "stock_name"])
        match = df[df["stock_code"].astype(str).str.zfill(6) == code]
        if not match.empty:
            n = str(match.iloc[0]["stock_name"])
            if n and n != code:
                return n
    except Exception:
        pass
    return stock_code


def get_fallback_prices(stock_codes: list) -> dict:
    """从因子评分数据获取兜底价格（最新close）"""
    if not FACTOR_LAB_SCORES.exists():
        return {}
    try:
        df = pd.read_csv(FACTOR_LAB_SCORES, usecols=["stock_code", "close", "date"])
        df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)
        latest_date = df["date"].max()
        latest = df[df["date"] == latest_date]
        result = {}
        for code in stock_codes:
            code = str(code).zfill(6)
            match = latest[latest["stock_code"] == code]
            if not match.empty:
                result[code] = {"current_price": float(match.iloc[0]["close"])}
        return result
    except Exception:
        return {}


def get_realtime_quotes(stock_codes: list) -> dict:
    """获取腾讯财经实时行情"""
    if not stock_codes:
        return {}
    
    # 构建腾讯secid列表 (sz=深市, sh=沪市)
    symbols = []
    for code in stock_codes:
        code = str(code).zfill(6)
        if code.startswith(('6', '9')):
            symbols.append(f"sh{code}")
        else:
            symbols.append(f"sz{code}")
    
    url = f"https://qt.gtimg.cn/q={','.join(symbols)}"
    
    result = {}
    session = requests.Session()
    session.trust_env = False  # 忽略系统代理
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.qq.com/",
    })
    
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            # 解析腾讯财经格式: v_sz002805="市场~名称~代码~当前价~昨收~开盘~...~涨跌额~涨跌幅%~..."
            for line in resp.text.strip().split(";"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                
                key, value = line.split("=", 1)
                value = value.strip('"')
                fields = value.split("~")
                
                if len(fields) >= 45:
                    code = fields[2]  # 股票代码
                    name = fields[1]  # 股票名称
                    current_price = float(fields[3]) if fields[3] else None  # 当前价
                    change_amount = float(fields[31]) if len(fields) > 31 and fields[31] else None  # 涨跌额
                    pct_chg = float(fields[32]) if len(fields) > 32 and fields[32] else None  # 涨跌幅%
                    
                    if code:
                        result[code] = {
                            "current_price": current_price,
                            "stock_name": name,
                            "pct_chg": pct_chg,
                            "change_amount": change_amount,
                        }
    except Exception:
        pass
    finally:
        session.close()
    
    return result


def cleanup_old_reports() -> dict:
    """清理超过 MAX_REPORT_AGE_DAYS 天的旧晨报"""
    if not REPORT_DIR.exists():
        return {"deleted": 0, "freed_bytes": 0}
    
    cutoff = datetime.now() - timedelta(days=MAX_REPORT_AGE_DAYS)
    deleted = 0
    freed_bytes = 0
    protected = {"latest.json", "latest.md"}
    
    for file_path in REPORT_DIR.iterdir():
        if file_path.name in protected:
            continue
        
        # 尝试从文件名解析日期 (YYYY-MM-DD.json/md)
        try:
            date_str = file_path.stem
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                size = file_path.stat().st_size
                file_path.unlink()
                deleted += 1
                freed_bytes += size
        except ValueError:
            # 不是标准日期格式的文件，跳过
            continue
    
    return {"deleted": deleted, "freed_bytes": freed_bytes}


def load_latest_scores() -> pd.DataFrame:
    """加载最新因子评分"""
    if not FACTOR_LAB_SCORES.exists():
        return pd.DataFrame()
    df = pd.read_csv(FACTOR_LAB_SCORES)
    return df


def load_factor_summary() -> dict:
    """加载因子实验室摘要"""
    if not FACTOR_LAB_SUMMARY.exists():
        return {}
    with open(FACTOR_LAB_SUMMARY, "r", encoding="utf-8") as f:
        return json.load(f)


def load_virtual_positions() -> pd.DataFrame:
    """加载虚拟交易持仓"""
    if not VIRTUAL_TRADING_DB.exists():
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(str(VIRTUAL_TRADING_DB))
        positions = pd.read_sql("SELECT * FROM positions", conn)
        conn.close()
        return positions
    except Exception:
        return pd.DataFrame()


def get_top_recommendations(scores_df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """获取Top N推荐股票"""
    if scores_df.empty:
        return pd.DataFrame()
    
    # 筛选有分数的最新日期数据
    valid = scores_df[scores_df["score"].notna()].copy()
    if valid.empty:
        return pd.DataFrame()
    
    latest_date = valid["date"].max()
    latest = valid[valid["date"] == latest_date].copy()
    
    # 按分数排序
    latest = latest.sort_values("score", ascending=False)
    
    # 添加信号标记
    latest["signal"] = (latest["daily_rank"] <= 5).astype(int)
    
    return latest.head(top_n)


def get_position_holding_info(positions_df: pd.DataFrame, stock_code: str) -> dict:
    """获取股票持仓信息"""
    if positions_df.empty:
        return {"held": False, "strategies": []}
    
    held = positions_df[positions_df["symbol"] == stock_code]
    if held.empty:
        return {"held": False, "strategies": []}
    
    strategies = []
    for _, row in held.iterrows():
        strategies.append({
            "strategy": row.get("strategy_id", ""),
            "shares": int(row.get("shares", 0)),
            "cost_price": float(row.get("cost_price", 0)),
            "current_price": float(row.get("current_price", 0)),
            "entry_date": row.get("entry_date", ""),
        })
    
    return {"held": True, "strategies": strategies}


def generate_market_overview(scores_df: pd.DataFrame) -> dict:
    """生成市场概览"""
    if scores_df.empty:
        return {"total_stocks": 0, "signal_count": 0, "avg_score": 0}
    
    latest_date = scores_df["date"].max()
    latest = scores_df[scores_df["date"] == latest_date]
    
    signal_count = int((latest["daily_rank"] <= 5).sum())
    avg_score = float(latest["score"].mean()) if "score" in latest.columns else 0
    
    return {
        "date": latest_date,
        "total_stocks": len(latest),
        "signal_count": signal_count,
        "avg_score": round(avg_score, 4),
    }


def generate_morning_report(date_str: str = None) -> dict:
    """生成晨报"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 加载数据
    scores_df = load_latest_scores()
    factor_summary = load_factor_summary()
    positions_df = load_virtual_positions()
    
    # 获取推荐
    recommendations = get_top_recommendations(scores_df, top_n=10)
    
    # 获取市场概览
    market_overview = generate_market_overview(scores_df)
    
    # 获取实时行情
    stock_codes = [str(row.get("stock_code", "")).zfill(6) for _, row in recommendations.iterrows()]
    realtime_quotes = get_realtime_quotes(stock_codes)
    fallback_prices = get_fallback_prices(stock_codes)
    
    # 构建推荐列表
    rec_list = []
    for _, row in recommendations.iterrows():
        stock_code = str(row.get("stock_code", "")).zfill(6)
        holding_info = get_position_holding_info(positions_df, stock_code)
        
        # 股票名称：本地映射 > 实时行情 > CSV
        stock_name = get_stock_name_local(stock_code)
        quote = realtime_quotes.get(stock_code, {})
        if quote.get("stock_name"):
            stock_name = quote["stock_name"]
        
        # 价格：实时行情 > 兜底价格
        current_price = quote.get("current_price")
        pct_chg = quote.get("pct_chg")
        change_amount = quote.get("change_amount")
        if current_price is None:
            fallback = fallback_prices.get(stock_code, {})
            current_price = fallback.get("current_price")
        
        rec_list.append({
            "rank": int(row.get("daily_rank", 0)),
            "stock_code": stock_code,
            "stock_name": stock_name,
            "score": round(float(row.get("score", 0)), 4),
            "signal": int(row.get("signal", 0)),
            "held": holding_info["held"],
            "holding_strategies": [s["strategy"] for s in holding_info["strategies"]],
            "recommendation": "持有" if holding_info["held"] else "关注",
            "current_price": quote.get("current_price"),
            "pct_chg": quote.get("pct_chg"),
            "change_amount": quote.get("change_amount"),
        })
    
    # 获取因子状态
    summary_data = factor_summary.get("summary", {})
    factor_status = {
        "run_id": summary_data.get("run_id", ""),
        "best_factor": summary_data.get("best_factor", ""),
        "test_rank_ic": round(float(summary_data.get("best_model_test_rank_ic", 0)), 4),
        "test_top20_ret": round(float(summary_data.get("best_model_test_top20_ret", 0)), 4),
        "model_recipe": summary_data.get("model_recipe", {}),
        "generated_at": summary_data.get("generated_at", ""),
    }
    
    # 构建报告
    report = {
        "report_date": date_str,
        "generated_at": datetime.now().isoformat(),
        "market_overview": market_overview,
        "factor_status": factor_status,
        "recommendations": rec_list,
        "risk_warnings": [],
    }
    
    # 风险警告
    if factor_status["test_rank_ic"] < 0.03:
        report["risk_warnings"].append("因子RankIC较低，模型预测能力有限，建议谨慎参考")
    
    high_vol = [r for r in rec_list if r.get("score", 0) > 0.9]
    if len(high_vol) > 3:
        report["risk_warnings"].append("高分股票较多，注意分散风险")
    
    return report


def format_markdown_report(report: dict) -> str:
    """格式化Markdown报告"""
    lines = [
        f"# 📊 量化晨报 - {report['report_date']}",
        "",
        f"生成时间: {report['generated_at']}",
        "",
        "## 📈 市场概览",
        "",
        f"- 股票总数: {report['market_overview']['total_stocks']}",
        f"- 信号股票: {report['market_overview']['signal_count']}",
        f"- 平均分数: {report['market_overview']['avg_score']}",
        "",
        "## 🔬 因子状态",
        "",
        f"- 运行ID: {report['factor_status']['run_id']}",
        f"- 最佳因子: {report['factor_status']['best_factor']}",
        f"- Test RankIC: {report['factor_status']['test_rank_ic']}",
        f"- Test Top20收益: {report['factor_status']['test_top20_ret']}",
        "",
        "## 🎯 今日Top 10推荐",
        "",
        "| 排名 | 代码 | 名称 | 分数 | 信号 | 持仓 | 建议 |",
        "|------|------|------|------|------|------|------|",
    ]
    
    for rec in report["recommendations"]:
        lines.append(
            f"| {rec['rank']} | {rec['stock_code']} | {rec['stock_name']} | "
            f"{rec['score']} | {'✅' if rec['signal'] else '❌'} | "
            f"{'✅' if rec['held'] else '❌'} | {rec['recommendation']} |"
        )
    
    if report["risk_warnings"]:
        lines.extend([
            "",
            "## ⚠️ 风险提示",
            "",
        ])
        for warning in report["risk_warnings"]:
            lines.append(f"- {warning}")
    
    lines.extend([
        "",
        "---",
        "*本报告由量化系统自动生成，仅供参考，不构成投资建议*",
    ])
    
    return "\n".join(lines)


def save_report(report: dict, markdown: str, date_str: str = None) -> dict:
    """保存报告到文件"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 保存JSON
    json_path = REPORT_DIR / f"{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # 保存Markdown
    md_path = REPORT_DIR / f"{date_str}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    
    # 更新latest链接
    latest_json = REPORT_DIR / "latest.json"
    latest_md = REPORT_DIR / "latest.md"
    
    import shutil
    shutil.copy2(json_path, latest_json)
    shutil.copy2(md_path, latest_md)
    
    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
        "latest_json": str(latest_json),
        "latest_md": str(latest_md),
    }


def generate_and_save(date_str: str = None) -> dict:
    """生成并保存晨报"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    report = generate_morning_report(date_str)
    markdown = format_markdown_report(report)
    paths = save_report(report, markdown, date_str)
    
    # 清理旧报告
    cleanup_result = cleanup_old_reports()
    
    return {
        "status": "success",
        "report": report,
        "paths": paths,
        "cleanup": cleanup_result,
    }


if __name__ == "__main__":
    result = generate_and_save()
    print(json.dumps(result, ensure_ascii=False, indent=2))
