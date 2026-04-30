import pandas as pd
import numpy as np
import os
from engine import BacktestEngine, CostModel
from strategies.extra_strategies_pro_plus import (
    calculate_ai_ml_signals_pro_plus,
    calculate_ai_adaptive_signals_pro_plus,
    calculate_blackhorse_signals_pro_plus
)

def run_decade_pro_plus_benchmark():
    data_dir = "data_cache/decade_study"
    output_dir = "../results/quant-factor-mining/reports/decade_study_pro_plus"
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. 加载数据
    all_data = []
    for f in os.listdir(data_dir):
        if f.endswith(".parquet"):
            all_data.append(pd.read_parquet(os.path.join(data_dir, f)))
    full_df = pd.concat(all_data).sort_values('date')
    
    # 2. 回测配置 (实盘标准成本：万3, 0.1%滑点)
    start_date = "2016-01-01"
    end_date = "2026-04-20"
    initial_capital = 1000000
    cost_model = CostModel(commission_rate=0.0003, slippage_rate=0.001)
    
    strategies = {
        "G_Defender_Pro_Plus": calculate_ai_ml_signals_pro_plus,
        "G_Midfield_Pro_Plus": calculate_ai_adaptive_signals_pro_plus,
        "G_Forward_Pro_Plus": calculate_blackhorse_signals_pro_plus
    }
    
    results = []
    for name, func in strategies.items():
        print(f"Executing Decade Run for {name} (Soccer Team Pro++)...")
        try:
            strat_df = func(full_df.copy())
            
            def signal_func(date, day_data):
                # 统一限制持仓 3 只，追求高确定性
                buys = day_data[day_data['signal'] == 1].sort_values('score', ascending=False)['stock_code'].tolist()
                active = buys[:3]
                if not active: return {}
                return {code: 1.0/len(active) for code in active}

            engine = BacktestEngine(initial_capital=initial_capital, cost_model=cost_model)
            res = engine.run_backtest(strat_df, signal_func, start_date, end_date)
            
            results.append({
                "Strategy": name,
                "Total Return": res['total_return'],
                "Sharpe": res['summary']['sharpe_ratio'],
                "Max Drawdown": res['summary']['max_drawdown'],
                "Trades": len(res['trades'])
            })
            
            # 保存净值
            history_df = pd.DataFrame(res['history'])
            history_df.to_csv(os.path.join(output_dir, f"equity_curve_{name}.csv"))

        except Exception as e:
            print(f"Failed {name}: {e}")

    results_df = pd.DataFrame(results).sort_values("Sharpe", ascending=False)
    results_df.to_markdown(os.path.join(output_dir, "decade_pro_plus_summary.md"), index=False)
    print(f"Decade Pro++ study complete. Results: {output_dir}")

if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    run_decade_pro_plus_benchmark()
