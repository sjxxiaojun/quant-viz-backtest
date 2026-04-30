import pandas as pd
import numpy as np
import os
from engine import BacktestEngine, CostModel
from strategies.extra_strategies import calculate_blackhorse_signals

def run_blackhorse_3_0_backtest():
    data_dir = "data_cache/blackhorse_study"
    output_dir = "../results/quant-factor-mining/reports/blackhorse_3_0"
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. 加载数据
    all_data = []
    for f in os.listdir(data_dir):
        if f.endswith(".parquet"):
            all_data.append(pd.read_parquet(os.path.join(data_dir, f)))
    full_df = pd.concat(all_data).sort_values('date')
    
    # 2. 回测配置 (万3, 0.1%滑点)
    start_date = "2023-01-01"
    end_date = "2026-04-20"
    initial_capital = 1000000
    cost_model = CostModel(commission_rate=0.0003, slippage_rate=0.001)
    
    print("Hunting with AI 3.0 (Blackhorse Hunter) on high-growth sectors...")
    strat_df = calculate_blackhorse_signals(full_df.copy())
    
    def signal_func(date, day_data):
        # 选出 Top 3 潜力黑马
        buys = day_data[day_data['signal'] == 1].sort_values('score', ascending=False)['stock_code'].tolist()
        active = buys[:3]
        if not active: return {}
        return {code: 1.0/len(active) for code in active}

    engine = BacktestEngine(initial_capital=initial_capital, cost_model=cost_model)
    res = engine.run_backtest(strat_df, signal_func, start_date, end_date)
    
    # 3. 结果提取
    report = f"""# AI 3.0 黑马猎人专项回测报告 (2023-2026)
## 1. 行业覆盖: 低空经济 + AI 算力 (高弹性标的)
## 2. AI 3.0 绩效总结
- **累计收益率**: {res['total_return']*100:.2f}%
- **夏普比率**: {res['summary']['sharpe_ratio']:.2f}
- **最大回撤**: {res['summary']['max_drawdown']*100:.2f}%
- **持仓胜率 (估计)**: {len([t for t in res['trades'] if t['side']=='sell']) / max(len(res['trades'])/2, 1) * 100:.1f}%

## 3. 猎杀成果表 (交易最活跃标的)
"""
    if res['trades']:
        trades_df = pd.DataFrame(res['trades'])
        if 'stock_code' in trades_df.columns:
            counts = trades_df['stock_code'].value_counts().head(8)
            report += counts.to_markdown()
    else:
        report += "\n*未触发猎杀信号，说明当前参数下黑马尚未启动或已过热。*"
    
    with open(os.path.join(output_dir, "blackhorse_3_0_report.md"), "w") as f:
        f.write(report)
        
    print(f"Blackhorse 3.0 study complete. Report: {output_dir}")

if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    run_blackhorse_3_0_backtest()
