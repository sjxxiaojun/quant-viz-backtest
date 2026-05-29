import pandas as pd
import numpy as np
from pathlib import Path
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("DataSentinel")

class DataSentinel:
    def __init__(self, data_lake_dir: str = "/Users/gdxj/quant_data_lake"):
        self.data_lake_dir = Path(data_lake_dir)
        self.a_share_dir = self.data_lake_dir 
        self.etf_dir = self.data_lake_dir / "etf"

    def check_data_health(self, target_date: str) -> dict:
        """运行全面的数据健康检查"""
        results = {
            "target_date": target_date,
            "timestamp": datetime.now().isoformat(),
            "a_share": self._check_asset_group(self.a_share_dir, target_date, "A股"),
            "etf": self._check_asset_group(self.etf_dir, target_date, "ETF"),
        }
        
        # 整体评分
        total_checked = results["a_share"]["checked_count"] + results["etf"]["checked_count"]
        total_issues = results["a_share"]["issue_count"] + results["etf"]["issue_count"]
        
        results["health_score"] = max(0, 100 - (total_issues / max(1, total_checked) * 100))
        results["status"] = "healthy" if results["health_score"] > 95 else "warning" if results["health_score"] > 80 else "critical"
        
        return results

    def _check_asset_group(self, directory: Path, target_date: str, label: str) -> dict:
        if not directory.exists():
            return {"error": f"{label} 目录不存在", "checked_count": 0, "issue_count": 0}

        files = list(directory.glob("*.parquet"))
        if not files:
            return {"error": f"{label} 无数据文件", "checked_count": 0, "issue_count": 0}

        # 采样检查
        sample_size = min(len(files), 100)
        import random
        sample_files = random.sample(files, sample_size)
        
        issues = []
        for f in sample_files:
            try:
                df = pd.read_parquet(f)
                if df.empty:
                    issues.append(f"{f.name}: 文件为空")
                    continue
                
                # 1. 检查目标日期是否存在
                if target_date not in df["date"].values:
                    issues.append(f"{f.name}: 缺失目标日期 {target_date}")
                
                # 2. 检查价格异常
                latest = df.iloc[-1]
                if latest["close"] <= 0:
                    issues.append(f"{f.name}: 最新价格异常 {latest['close']}")
                
                # 3. 检查成交量与成交额
                if latest["volume"] > 0 and latest["amount"] == 0:
                    issues.append(f"{f.name}: 有量无额异常")
                    
            except Exception as e:
                issues.append(f"{f.name}: 读取失败 {e}")

        return {
            "label": label,
            "checked_count": sample_size,
            "issue_count": len(issues),
            "issues_tail": issues[:10],
            "coverage_ratio": (sample_size - len(issues)) / sample_size if sample_size > 0 else 0
        }

if __name__ == "__main__":
    sentinel = DataSentinel()
    # 尝试检查上一个交易日
    # 假设今天是 2026-05-20，检查 2026-05-19
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(sentinel.check_data_health(yesterday))
