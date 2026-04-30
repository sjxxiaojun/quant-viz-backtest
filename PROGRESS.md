# Gemini量化pro - 项目进度记录 (2026-04-21)

### 🚀 当前状态 (V4.8 Final Evolution)
系统已进化为“全盘数据湖”架构，前端采用“策略大厅+仿真控制台”双层结构。

### 🔧 环境配置 (恢复关键)
- **后端 (API)**: Port 8080 (FastAPI)
- **前端 (Web)**: Port 5173 (React/Vite)
- **数据湖存储**: `/Users/gdxj/quant_data_lake` (已整合 A 股 + 全量 ETF)
- **数据范围**: 2022-01-01 至今，涵盖 PE/PB/换手/PS/PCF/ST 等 11+ 核心因子。

### 📊 策略矩阵 (11套)
1. **AI模型**: ETF抄底王(进攻/稳定)、AI机器学习合成。
2. **信号工厂**: 一夜持股、弱转强、涨停十字星。
3. **经典量化**: 行业优选、高频海龟、HFMR、超跌反转、趋势增强(ATM)。

### 🛠 重启后恢复步骤
开机后请分别在两个窗口执行：

1. **同步数据湖 (继续下载)**:
   ```bash
   cd ~/quant-viz-backtest/backend
   ./venv/bin/python3 download_full_market.py
   ```
2. **启动回测工作站**:
   ```bash
   cd ~/quant-viz-backtest/backend && ./venv/bin/python3 main.py
   # 另一个窗口
   cd ~/quant-viz-backtest/frontend && npm run dev
   ```

### 📋 存档记录
- 缓存同步进度：约 200+/7273 (正在后台多线程下载中)
- 键盘快捷输入：已实装
- 鼠标悬浮交易详情：已实装
