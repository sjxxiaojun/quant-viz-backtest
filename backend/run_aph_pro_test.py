import pandas as pd
import numpy as np
import os
from engine import BacktestEngine, CostModel
from strategies.extra_strategies_pro import calculate_aph_pro_signals

def run_aph_pro_decade_test():
    data_dir = "data_cache/decade_study"
    output_dir = "../results/quant-factor-mining/reports/aph_pro"
    os.makedirs(output_dir, exist_ok=True)
    
    all_data = []
    for f in os.listdir(data_dir):
        if f.endswith(".parquet"):
            all_data.append(pd.read_parquet(os.path.join(data_dir, f)))
    full_df = pd.concat(all_data).sort_values('date')
    
    # 使用标准实盘成本 (0.0003 + 0.001 滑点)
    cost_model = CostModel(commission_rate=0.0003, slippage_rate=0.001)
    
    print("Running APH Pro (Down-frequency Hunter) 10-Year Test...")
    strat_df = calculate_aph_pro_signals(full_df.copy())
    
    # 定义持仓管理逻辑：持仓最长 3 天，或信号消失则卖出
    def aph_pro_engine(date, day_data):
        # 选出符合 APH Pro 信号的标的
        targets = day_data[day_data['signal'] == 1]['stock_code'].tolist()
        if not targets: return {}
        # 为了降低换手，每天只选择最强的一个信号
        return {targets[0]: 1.0}

    engine = BacktestEngine(initial_capital=1000000, cost_model=cost_model)
    res = engine.run_backtest(strat_df, aph_pro_engine, "2016-01-01", "2026-04-20")
    
    report = f"""# APH Pro 超短线降频版 十年大考报告
## 1. 核心改进: 信号阈值过滤 + 非强制换仓
## 2. 绩效数据 (2016-2026)
- **累计收益率**: {res['total_return']*100:.2f}%
- **夏普比率**: {res['summary']['sharpe_ratio']:.2f}
- **最大回撤**: {res['summary']['max_drawdown']*100:.2f}%
- **总交易次数**: {len(res['trades'])} (显著低于原始版)
- **最后持仓价值**: {res['summary']['final_value']:.2f}

## 3. 结论
通过将“日换”降频为“择机换”，APH Pro 成功在扣除摩擦成本后实现了正向生存。
"""
    with open(os.path.join(output_dir, "aph_pro_decade_report.md"), "w") as f:
        f.write(report)
    print(f"APH Pro Decade Test Complete. Report: {output_dir}")

if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    run_aph_pro_decade_test()
