import pandas as pd
import numpy as np
import os
from strategies.extra_strategies_pro import calculate_blackhorse_signals_pro, calculate_ai_ml_signals_pro

def generate_pre_market_alerts():
    # 扫描池：合并之前的黑马池与电力池
    data_dirs = [
        "data_cache/blackhorse_study",
        "data_cache/decade_study"
    ]
    
    all_data = []
    for d in data_dirs:
        if not os.path.exists(d): continue
        for f in os.listdir(d):
            if f.endswith(".parquet"):
                all_data.append(pd.read_parquet(os.path.join(d, f)))
    
    full_df = pd.concat(all_data).sort_values('date')
    
    # 1. 计算 AI 3.0 Pro 黑马猎人信号
    print("Scanning for Blackhorse Hunter signals...")
    bh_df = calculate_blackhorse_signals_pro(full_df.copy())
    latest_bh = bh_df[bh_df['date'] == bh_df['date'].max()]
    top_bh = latest_bh[latest_bh['score'] > 0.5].nlargest(5, 'score')
    
    # 2. 计算 AI 2.0 Pro 防御型加固信号
    print("Scanning for AI ML 2.0 Pro defense signals...")
    ml_df = calculate_ai_ml_signals_pro(full_df.copy())
    latest_ml = ml_df[ml_df['date'] == ml_df['date'].max()]
    top_ml = latest_ml[latest_ml['score'] > 0].nlargest(5, 'score')
    
    # 3. 输出报告
    report = f"# 🚀 Gemini量化Pro: 2026-04-21 盘前预警报告\n"
    report += f"**生成时间**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n"
    report += f"**最新交易日数据**: {bh_df['date'].max()}\n\n"
    
    report += "## 🏹 AI 3.0 黑马猎人 (进攻型 - 高弹性/科技)\n"
    if not top_bh.empty:
        report += top_bh[['stock_code', 'stock_name', 'score', 'rsi_fast']].to_markdown(index=False)
    else:
        report += "*当前行情处于高位震荡，黑马猎人建议空仓观望或信号未达标。*\n"
        
    report += "\n## 🛡️ AI 2.0 机器学习 (防御型 - 价值/稳健)\n"
    if not top_ml.empty:
        report += top_ml[['stock_code', 'stock_name', 'score']].to_markdown(index=False)
    else:
        report += "*未发现符合低波价值自愈基因的标的。*\n"
        
    report += "\n\n**投资建议**: 开盘观察黑马池中 RSI 较低的标的。若出现放量突破，可分批建仓。保持 T+1 纪律。"
    
    output_path = "../results/quant-factor-mining/reports/daily_pre_market.md"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report)
    
    print(f"Pre-market report generated: {output_path}")

if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    generate_pre_market_alerts()
