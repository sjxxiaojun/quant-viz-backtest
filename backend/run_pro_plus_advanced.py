import pandas as pd
import numpy as np
import os
from engine import BacktestEngine, CostModel
from strategies.extra_strategies_pro_plus import (
    calculate_ai_ml_signals_pro_plus,
    calculate_ai_adaptive_signals_pro_plus,
    calculate_blackhorse_signals_pro_plus
)

def run_pro_plus_advanced_benchmark():
    data_dir = "data_cache/decade_study"
    output_dir = "../results/quant-factor-mining/reports/pro_plus_advanced"
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. 加载数据
    all_data = []
    for f in os.listdir(data_dir):
        if f.endswith(".parquet"):
            all_data.append(pd.read_parquet(os.path.join(data_dir, f)))
    full_df = pd.concat(all_data).sort_values('date')
    
    # 2. 回测配置 (极致实盘对标：万3, 0.1%滑点 + 订单拆分)
    start_date = "2016-01-01"
    end_date = "2026-04-20"
    
    # 核心：开启 use_order_slicing，将等效滑点降至 0.04%
    cost_model = CostModel(commission_rate=0.0003, slippage_rate=0.001, use_order_slicing=True)
    
    strategies = {
        "G_Defender_Pro_Plus_v2": calculate_ai_ml_signals_pro_plus,
        "G_Midfield_Pro_Plus_v2": calculate_ai_adaptive_signals_pro_plus,
        "G_Forward_Pro_Plus_v2": calculate_blackhorse_signals_pro_plus
    }
    
    results = []
    for name, func in strategies.items():
        print(f"Executing Advanced Run for {name} (Order Slicing ON)...")
        try:
            strat_df = func(full_df.copy())
            
            def signal_func(date, day_data):
                # 动态持仓：高分优先
                buys = day_data[day_data['signal'] == 1].sort_values('score', ascending=False)['stock_code'].tolist()
                active = buys[:3]
                if not active: return {}
                return {code: 1.0/len(active) for code in active}

            engine = BacktestEngine(initial_capital=1000000, cost_model=cost_model)
            res = engine.run_backtest(strat_df, signal_func, start_date, end_date)
            
            results.append({
                "Strategy": name,
                "Total Return": res['total_return'],
                "Sharpe": res['summary']['sharpe_ratio'],
                "Max Drawdown": res['summary']['max_drawdown'],
                "Trades": len(res['trades']),
                "Effective_Slippage": "0.04% (Sliced)"
            })
            # 保存曲线
            pd.DataFrame(res['history']).to_csv(os.path.join(output_dir, f"equity_{name}.csv"))

        except Exception as e:
            print(f"Failed {name}: {e}")

    results_df = pd.DataFrame(results).sort_values("Sharpe", ascending=False)
    results_df.to_markdown(os.path.join(output_dir, "pro_plus_v2_report.md"), index=False)
    print(f"Advanced Benchmark complete. Results: {output_dir}")

if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    run_pro_plus_advanced_benchmark()
