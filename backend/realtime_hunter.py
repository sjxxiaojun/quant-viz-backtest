import os
import time
import pywencai
import pandas as pd

def scan_realtime_blackhorse():
    print("=== 小G前锋：开盘实时黑马扫描 ===")
    
    # 从环境变量读取 cookie，如果为空则提示
    cookie = os.environ.get('WENCAI_COOKIE', '')
    if not cookie:
        print("警告: 缺少 WENCAI_COOKIE 环境变量。请确保已登录同花顺问财并提取 Cookie。")
        return

    # 小G前锋的核心猎杀条件 (翻译为自然语言给问财)
    # 1. 新高 (创5日新高)
    # 2. 动量加速度 (今日涨幅比昨日涨幅大)
    # 3. 放量 (今日量比 > 1.5)
    # 4. 板块过滤 (属于机器人或固态电池概念)
    # 5. 剔除一字涨停 (确保能买入)
    
    queries = [
        "机器人概念，创5日新高，量比大于1.5，非一字涨停，今日涨幅排序",
        "固态电池概念，创5日新高，量比大于1.5，非一字涨停，今日涨幅排序",
        "低空经济概念，创5日新高，量比大于1.5，非一字涨停，今日涨幅排序",
        "AI算力概念，创5日新高，量比大于1.5，非一字涨停，今日涨幅排序"
    ]
    
    all_results = []
    
    for q in queries:
        print(f"\n>> 正在扫描: {q.split('，')[0]}...")
        try:
            res = pywencai.get(query=q, cookie=cookie, no_detail=True)
            if res is not None and not res.empty:
                print(f"✅ 发现 {len(res)} 只符合条件的黑马标的！")
                
                # 提取核心展示字段 (问财返回的列名通常很长，我们做一下动态匹配)
                display_cols = []
                for col in res.columns:
                    if any(k in col for k in ['股票代码', '股票简称', '涨跌幅', '量比', '现价', '最新价']):
                        display_cols.append(col)
                
                if display_cols:
                    print(res[display_cols].head(3).to_markdown(index=False))
                else:
                    print(res.head(3))
            else:
                print("❌ 该板块当前暂无标的符合极致爆发条件。")
        except Exception as e:
            print(f"扫描出错: {e}")
        
        # 遵守规则：请求间隔
        time.sleep(2.5)
        
    print("\n=== 扫描结束 ===")

if __name__ == '__main__':
    scan_realtime_blackhorse()
