import pandas as pd
import numpy as np
import os
from engine import BacktestEngine, CostModel
from strategies.extra_strategies import (
    calculate_reversal_vol_signals, 
    calculate_turtle_signals, 
    calculate_hfmr_signals,
    calculate_ai_ml_signals,
    calculate_ai_adaptive_signals
)

def run_extreme_stress_test():
    data_dir = "data_cache/decade_study"
    output_dir = "../results/quant-factor-mining/reports/stress_test"
    os.makedirs(output_dir, exist_ok=True)
    
    all_data = []
    for f in os.listdir(data_dir):
        if f.endswith(".parquet"):
            all_data.append(pd.read_parquet(os.path.join(data_dir, f)))
    full_df = pd.concat(all_data).sort_values('date')
    
    # 极端成本模型 (佣金万8, 滑点0.5%)
    extreme_costs = CostModel(commission_rate=0.0008, slippage_rate=0.005)
    
    strategies = {
        "AI_ML_2.0": calculate_ai_ml_signals,
        "AI_Adaptive_Regime": calculate_ai_adaptive_signals,
        "HF_Mean_Reversion": calculate_hfmr_signals,
        "Reversal_Spike": calculate_reversal_vol_signals
    }
    
    results = []
    for name, func in strategies.items():
        print(f"Stress Testing Strategy: {name}...")
        try:
            strat_df = func(full_df.copy())
            
            def signal_func(date, day_data):
                buys = day_data[day_data['signal'] == 1]['stock_code'].tolist()
                active = buys[:5]
                if not active: return {}
                return {code: 1.0/len(active) for code in active}

            engine = BacktestEngine(initial_capital=1000000, cost_model=extreme_costs)
            res = engine.run_backtest(strat_df, signal_func, "2016-01-01", "2026-04-20")
            
            results.append({
                "Strategy": name,
                "Net Return (Extreme)": res['total_return'],
                "Max Drawdown": res['summary']['max_drawdown'],
                "Trades": len(res['trades'])
            })
        except Exception as e:
            print(f"Failed: {e}")

    results_df = pd.DataFrame(results).sort_values("Net Return (Extreme)", ascending=False)
    results_df.to_markdown(os.path.join(output_dir, "survival_report.md"), index=False)
    print("Stress test complete.")

if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    run_extreme_stress_test()
