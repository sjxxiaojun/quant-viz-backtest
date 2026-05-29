import os
import pandas as pd
import numpy as np
from engine import BacktestEngine, CostModel
from strategies.news_sentiment_strategy import calculate_news_sentiment_signals

def run_sentiment_backtest():
    data_dir = "data_cache/decade_study"
    
    # 1. 加载 15 只样本股票的历史数据
    all_data = []
    for f in os.listdir(data_dir):
        if f.endswith(".parquet"):
            df_stock = pd.read_parquet(os.path.join(data_dir, f))
            # 确保代码是6位字符串
            if 'stock_code' in df_stock.columns:
                df_stock['stock_code'] = df_stock['stock_code'].astype(str).str.zfill(6)
            all_data.append(df_stock)
            
    full_df = pd.concat(all_data).sort_values('date')
    print(f"Loaded {len(all_data)} stocks, total {len(full_df)} rows of history K-line data.")
    
    # 2. 运行策略信号生成
    print("Calculating news sentiment signals...")
    strat_df = calculate_news_sentiment_signals(full_df)
    
    # 3. 设置回测撮合引擎与有状态选股回调（sell_on_minus_one 逻辑）
    current_portfolio = {} # 记录当前持仓
    
    def signal_func(date, day_data):
        nonlocal current_portfolio
        
        # 检查当前持仓股是否触发卖出信号 (-1)
        day_data_dict = day_data.set_index('stock_code').to_dict('index')
        to_remove = []
        for code in list(current_portfolio.keys()):
            if code in day_data_dict:
                # 触发卖出信号（或者大盘/个股条件跌破）
                if day_data_dict[code]['signal'] == -1:
                    to_remove.append(code)
            # 注意：若 code 不在 day_data_dict 中，属于个股停牌，在此处不剔除，保持原有持仓
                
        for code in to_remove:
            current_portfolio.pop(code, None)
            
        # 若有空余仓位，则补充买入信号
        slots_available = 3 - len(current_portfolio)
        if slots_available > 0:
            candidates = day_data[
                (day_data['signal'] == 1) & 
                (~day_data['stock_code'].isin(current_portfolio.keys()))
            ]
            if not candidates.empty:
                buys = candidates.nlargest(slots_available, 'score')
                for code in buys['stock_code'].tolist():
                    current_portfolio[code] = 1.0 # 占位
                    
        if not current_portfolio:
            return {}
            
        weight = 1.0 / len(current_portfolio)
        return {code: weight for code in current_portfolio.keys()}

    # 打印 2016-04-18 到 2016-04-25 期间 000001 的指标以 debug
    dbg_df = strat_df[(strat_df['stock_code'] == '000001') & (strat_df['date'] >= '2016-04-18') & (strat_df['date'] <= '2016-04-25')]
    print("\nDEBUG INFO for 000001:")
    print(dbg_df[['date', 'close', 'ma20', 'ma30', 'ma60', 'vol_ratio', 'vol_std', 'exit_cond', 'signal']])
    
    start_date = "2016-01-01"
    end_date = "2026-04-20"


    initial_capital = 1000000
    cost_model = CostModel(commission_rate=0.0003, slippage_rate=0.001)
    
    print(f"Running backtest from {start_date} to {end_date}...")
    engine = BacktestEngine(initial_capital=initial_capital, cost_model=cost_model)
    res = engine.run_backtest(strat_df, signal_func, start_date, end_date)
    
    summary = res.get('summary', {})
    
    print("\n================== BACKTEST RESULT ==================")
    print(f"Strategy: News Sentiment Alpha 2026")
    print(f"Total Return: {res.get('total_return', 0)*100:.2f}%")
    print(f"Annualized Return: {summary.get('annualized_return', 0)*100:.2f}%")
    print(f"Sharpe Ratio: {summary.get('sharpe_ratio', 0):.2f}")
    print(f"Max Drawdown: {summary.get('max_drawdown', 0)*100:.2f}%")
    print(f"Total Trades: {len(res.get('trades', []))}")
    print(f"Win Rate (胜率): {summary.get('win_rate', 0)*100:.2f}%")
    print("=====================================================")
    
    # 将结果保存到 reports 目录以记录性能
    output_dir = "../results/quant-factor-mining/reports/decade_study_pro_plus"
    os.makedirs(output_dir, exist_ok=True)
    history_df = pd.DataFrame(res['history'])
    history_df.to_csv(os.path.join(output_dir, "equity_curve_News_Sentiment_Alpha.csv"))
    
    # 打印前 5 笔交易以供审计
    trades = res.get('trades', [])
    if trades:
        print("\nFirst 5 trades:")
        for t in trades[:5]:
            print(t)

if __name__ == "__main__":
    run_sentiment_backtest()
