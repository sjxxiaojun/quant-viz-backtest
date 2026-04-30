import pandas as pd
import numpy as np
import os
from engine import BacktestEngine, CostModel
from strategies.atm_filter import calculate_atm_signals
from strategies.extra_strategies import (
    calculate_reversal_vol_signals, 
    calculate_turtle_signals, 
    calculate_hfmr_signals,
    calculate_sector_alpha_signals,
    calculate_ai_ml_signals,
    calculate_ai_adaptive_signals
)

def run_decade_benchmark():
    data_dir = "data_cache/decade_study"
    output_dir = "../results/quant-factor-mining/reports/decade_study"
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. 加载所有 10 年数据
    all_data = []
    for f in os.listdir(data_dir):
        if f.endswith(".parquet"):
            all_data.append(pd.read_parquet(os.path.join(data_dir, f)))
    
    full_df = pd.concat(all_data).sort_values('date')
    
    # 2. 定义测试区间
    start_date = "2016-01-01"
    end_date = "2026-04-20"
    initial_capital = 1000000
    
    # 定义分阶段统计
    periods = {
        "Overall (10Y)": ("2016-01-01", "2026-04-20"),
        "WhiteHorse_Bull (16-17)": ("2016-01-01", "2017-12-31"),
        "TradeWar_Bear (18)": ("2018-01-01", "2018-12-31"),
        "Structure_Bull (19-21)": ("2019-01-01", "2021-12-31"),
        "Volatility_Regime (22+)": ("2022-01-01", "2026-04-20")
    }
    
    strategies = {
        "ATM_Trend": calculate_atm_signals,
        "Reversal_Spike": calculate_reversal_vol_signals,
        "HighFreq_Turtle": calculate_turtle_signals,
        "HF_Mean_Reversion": calculate_hfmr_signals,
        "Sector_MultiFactor": calculate_sector_alpha_signals,
        "AI_ML_2.0": calculate_ai_ml_signals,
        "AI_Adaptive_Regime": calculate_ai_adaptive_signals
    }
    
    all_results = []
    cost_model = CostModel(commission_rate=0.0003, slippage_rate=0.001)
    
    for name, func in strategies.items():
        print(f"Executing Decade Run for Strategy: {name}...")
        try:
            # 计算全量信号
            strat_df = func(full_df.copy())
            
            def signal_func(date, day_data):
                buys = day_data[day_data['signal'] == 1]['stock_code'].tolist()
                sells = day_data[day_data['signal'] == -1]['stock_code'].tolist()
                # 简单逻辑：持仓前 5 只，平仓信号触发则卖出
                active = buys[:5]
                if not active: return {}
                return {code: 1.0/len(active) for code in active}

            engine = BacktestEngine(initial_capital=initial_capital, cost_model=cost_model)
            # 运行全量回测获取历史曲线
            full_res = engine.run_backtest(strat_df, signal_func, start_date, end_date)
            history_df = pd.DataFrame(full_res['history'])
            history_df['date'] = pd.to_datetime(history_df['date'])
            history_df['ret'] = history_df['total_value'].pct_change()
            
            # 分阶段统计
            for p_name, (p_start, p_end) in periods.items():
                mask = (history_df['date'] >= p_start) & (history_df['date'] <= p_end)
                p_history = history_df[mask]
                
                if p_history.empty: continue
                
                total_ret = (p_history['total_value'].iloc[-1] / p_history['total_value'].iloc[0]) - 1
                sharpe = (p_history['ret'].mean() / p_history['ret'].std() * np.sqrt(252)) if p_history['ret'].std() > 0 else 0
                max_dd = (p_history['total_value'] / p_history['total_value'].cummax() - 1).min()
                
                all_results.append({
                    "Strategy": name,
                    "Period": p_name,
                    "Total Return": total_ret,
                    "Sharpe": sharpe,
                    "Max Drawdown": max_dd
                })
            
            # 保存净值
            history_df.to_csv(os.path.join(output_dir, f"equity_curve_{name}.csv"))

        except Exception as e:
            print(f"Strategy {name} failed: {e}")

    results_df = pd.DataFrame(all_results)
    results_df.to_csv(os.path.join(output_dir, "decade_benchmark_results.csv"), index=False)
    
    # 生成透视表报告
    pivot_ret = results_df.pivot(index="Strategy", columns="Period", values="Total Return")
    pivot_sharpe = results_df.pivot(index="Strategy", columns="Period", values="Sharpe")
    
    report = "# 2016-2026 十年量化大回测报告\n\n"
    report += "## 1. 阶段累计收益对比\n\n" + pivot_ret.to_markdown() + "\n\n"
    report += "## 2. 阶段夏普比率对比\n\n" + pivot_sharpe.to_markdown() + "\n\n"
    
    with open(os.path.join(output_dir, "decade_study_report.md"), "w") as f:
        f.write(report)
        
    print(f"Decade study complete. Results: {output_dir}")

if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    run_decade_benchmark()
