import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
from engine import BacktestEngine, CostModel
from data_manager import DataManager
from strategies.atm_filter import calculate_atm_signals
from strategies.extra_strategies import (
    calculate_reversal_vol_signals, 
    calculate_turtle_signals, 
    calculate_hfmr_signals,
    calculate_sector_alpha_signals,
    calculate_ai_ml_signals,
    calculate_ai_adaptive_signals
)

def run_comprehensive_benchmark():
    dm = DataManager()
    output_dir = "../results/quant-factor-mining/reports/benchmark"
    os.makedirs(output_dir, exist_ok=True)
    
    # 统一测试参数
    stocks = ["600519", "000001", "300750", "600036", "601318", "601012", "002594", "600900", "688981", "002371"]
    start_date = "2024-01-01"
    end_date = "2025-12-31"
    initial_capital = 1000000
    
    # 获取数据 (含预热期)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    warmup_start = (start_dt - timedelta(days=150)).strftime("%Y-%m-%d")
    print(f"Fetching benchmark data for {len(stocks)} stocks...")
    df = dm.get_stock_pool_data(stocks, warmup_start, end_date)
    
    if df.empty:
        print("Error: No data fetched.")
        return

    # 定义策略字典
    strategies = {
        "ATM_Trend": calculate_atm_signals,
        "Reversal_Spike": calculate_reversal_vol_signals,
        "HighFreq_Turtle": calculate_turtle_signals,
        "HF_Mean_Reversion": calculate_hfmr_signals,
        "Sector_MultiFactor": calculate_sector_alpha_signals,
        "AI_ML_Static": calculate_ai_ml_signals,
        "AI_Adaptive_Regime": calculate_ai_adaptive_signals
    }
    
    benchmark_results = []
    
    # 实盘成本模型 (万3佣金, 0.1%滑点)
    cost_model = CostModel(commission_rate=0.0003, slippage_rate=0.001)
    
    for name, func in strategies.items():
        print(f"Benchmarking Strategy: {name}...")
        try:
            # 1. 计算信号
            strat_df = func(df.copy())
            
            # 2. 定义信号执行逻辑
            current_target_stocks = set()
            def signal_func(date, day_data):
                nonlocal current_target_stocks
                to_remove = set()
                for code in current_target_stocks:
                    stock_day = day_data[day_data['stock_code'] == code]
                    if not stock_day.empty and stock_day.iloc[0]['signal'] == -1:
                        to_remove.add(code)
                current_target_stocks -= to_remove
                buys = day_data[day_data['signal'] == 1]['stock_code'].tolist()
                for code in buys:
                    current_target_stocks.add(code)
                if not current_target_stocks: return {}
                active = list(current_target_stocks)[:5] # 限制持仓 5 只
                return {code: 1.0/len(active) for code in active}

            # 3. 运行引擎
            engine = BacktestEngine(initial_capital=initial_capital, cost_model=cost_model)
            res = engine.run_backtest(strat_df, signal_func, start_date, end_date)
            
            # 4. 提取关键指标
            benchmark_results.append({
                "Strategy": name,
                "Total Return": res['total_return'],
                "Sharpe": res['summary']['sharpe_ratio'],
                "Max Drawdown": res['summary']['max_drawdown'],
                "Trades": len(res['trades']),
                "Final Value": res['summary']['final_value']
            })
            
        except Exception as e:
            print(f"Strategy {name} failed: {e}")

    # 保存对比表
    results_df = pd.DataFrame(benchmark_results).sort_values("Total Return", ascending=False)
    results_df.to_csv(os.path.join(output_dir, "strategy_benchmark_comparison.csv"), index=False)
    
    # 生成 Markdown 报告
    markdown_report = "# 策略全量基准测试报告 (2024-2025)\n\n"
    markdown_report += "## 1. 测试环境说明\n"
    markdown_report += f"- **股票池**: 蓝筹+新能源+半导体 (10只)\n"
    markdown_report += f"- **回测时段**: {start_date} 至 {end_date}\n"
    markdown_report += "- **成本假设**: 佣金万3, 滑点0.1%\n"
    markdown_report += "- **最大仓位**: 5只个股等权\n\n"
    markdown_report += "## 2. 绩效对比排名\n\n"
    markdown_report += results_df.to_markdown(index=False)
    
    with open(os.path.join(output_dir, "benchmark_report.md"), "w") as f:
        f.write(markdown_report)
        
    print(f"Benchmark complete. Report saved to {output_dir}")

if __name__ == "__main__":
    # 进入 backend 目录运行
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    run_comprehensive_benchmark()
