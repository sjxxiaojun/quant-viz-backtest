import pandas as pd
import numpy as np
import os
from engine import BacktestEngine, CostModel
from strategies.extra_strategies_pro_plus import (
    calculate_ai_ml_signals_pro_plus,
    calculate_ai_adaptive_signals_pro_plus,
    calculate_blackhorse_signals_pro_plus
)

def run_real_performance_test():
    data_dir = "data_cache/decade_study"
    output_dir = "../results/quant-factor-mining/reports/real_performance_2022"
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. 加载 10 年混合数据集 (确保覆盖 2022-2026)
    all_data = []
    for f in os.listdir(data_dir):
        if f.endswith(".parquet"):
            all_data.append(pd.read_parquet(os.path.join(data_dir, f)))
    full_df = pd.concat(all_data).sort_values('date')
    
    # 2. 回测区间与资金 (2022年至今)
    start_date = "2022-01-01"
    end_date = "2026-04-20"
    initial_capital = 1000000
    
    # 3. 正常滑点配置 (万3佣金 + 万3滑点 + 开启订单拆分)
    # 等效冲击成本 = 0.0003 + (0.0003 * 0.5) = 0.00045 (万4.5)
    cost_model = CostModel(commission_rate=0.0003, slippage_rate=0.0003, use_order_slicing=True)
    
    strategies = {
        "小G前锋 (Blackhorse Pro++)": calculate_blackhorse_signals_pro_plus,
        "小G中场 (Adaptive Pro++)": calculate_ai_adaptive_signals_pro_plus,
        "小G后卫 (Defense Pro++)": calculate_ai_ml_signals_pro_plus
    }
    
    results = []
    for name, func in strategies.items():
        print(f"Testing real performance for: {name}...")
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
                "Total Return": f"{res['total_return']*100:.2f}%",
                "Ann. Return": f"{((1+res['total_return'])**(1/4.3) - 1)*100:.2f}%", # 约 4.3 年
                "Sharpe": round(res['summary']['sharpe_ratio'], 2),
                "Max Drawdown": f"{res['summary']['max_drawdown']*100:.2f}%",
                "Trades": len(res['trades'])
            })
            # 保存净值
            pd.DataFrame(res['history']).to_csv(os.path.join(output_dir, f"equity_{name}.csv"))

        except Exception as e:
            print(f"Failed {name}: {e}")

    results_df = pd.DataFrame(results)
    results_df.to_markdown(os.path.join(output_dir, "real_performance_report.md"), index=False)
    print(f"\nReal Performance Study Complete. Report saved to {output_dir}")
    print(results_df)

if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    run_real_performance_test()
