import pandas as pd
import numpy as np
import os
from engine import BacktestEngine, CostModel
from strategies.extra_strategies import calculate_ai_ml_signals

def run_blackhorse_backtest():
    data_dir = "data_cache/blackhorse_study"
    output_dir = "../results/quant-factor-mining/reports/blackhorse"
    os.makedirs(output_dir, exist_ok=True)
    
    all_data = []
    for f in os.listdir(data_dir):
        if f.endswith(".parquet"):
            all_data.append(pd.read_parquet(os.path.join(data_dir, f)))
    full_df = pd.concat(all_data).sort_values('date')
    
    start_date = "2023-01-01"
    end_date = "2026-04-20"
    initial_capital = 1000000
    cost_model = CostModel(commission_rate=0.0003, slippage_rate=0.001)
    
    print("Running AI 2.0 on Blackhorse sectors...")
    strat_df = calculate_ai_ml_signals(full_df.copy())
    
    def signal_func(date, day_data):
        # 选出 Top 3 潜力黑马
        buys = day_data[day_data['signal'] == 1].sort_values('score', ascending=False)['stock_code'].tolist()
        active = buys[:3]
        if not active: return {}
        return {code: 1.0/len(active) for code in active}

    engine = BacktestEngine(initial_capital=initial_capital, cost_model=cost_model)
    res = engine.run_backtest(strat_df, signal_func, start_date, end_date)
    
    report = f"""# 黑马板块专项回测报告 (2023-2026)
## 1. 行业覆盖: 低空经济 + AI 算力
## 2. AI 2.0 绩效总结
- **累计收益率**: {res['total_return']*100:.2f}%
- **夏普比率**: {res['summary']['sharpe_ratio']:.2f}
- **最大回撤**: {res['summary']['max_drawdown']*100:.2f}%
- **最后持仓价值**: {res['summary']['final_value']:.2f}

## 3. 交易统计
"""
    if res['trades']:
        trades_df = pd.DataFrame(res['trades'])
        # 修正：如果 DataFrame 存在，统计成交次数最多的标的
        if 'stock_code' in trades_df.columns:
            counts = trades_df['stock_code'].value_counts().head(5)
            report += "### 成交最活跃标的 (次数):\n" + counts.to_markdown()
    else:
        report += "\n*该时段内未触发符合条件的 AI 2.0 交易信号。*"
    
    with open(os.path.join(output_dir, "blackhorse_report.md"), "w") as f:
        f.write(report)
        
    print(f"Blackhorse study complete. Report: {output_dir}")

if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    run_blackhorse_backtest()
