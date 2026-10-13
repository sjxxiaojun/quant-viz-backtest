# momo quant pro · 本地量化研究终端

面向个人使用的 A 股与 ETF 日线回测、因子研究和模拟账户工具。使用 FastAPI、React/Vite、SQLite 与 Parquet；研究计算无需外部大模型。

## 启动

后端使用 **Python 3.12**，旧 `backend/venv` 不会被覆盖。

```bash
cd backend
uv sync --locked --python 3.12
uv run --locked uvicorn main:app --host 127.0.0.1 --port 8080
```

另开终端启动前端：

```bash
cd frontend
npm ci
npm run dev
```

也可使用 `backend/launch_backend.sh`；该脚本读取本机 `.env.local`，选择新 `.venv`。兼容安装入口为 `backend/requirements.txt`，由 `uv.lock` 导出，同样要求 Python 3.12。

## 工作流

- **行情概览**：展示真实缓存日期，区分历史快照与最近完成交易日。
- **策略回测**：配置策略、日期、持仓与费用；恢复保存的实际参数和完整结果。
- **策略比较**：查看资金曲线、回撤、基准、成本与换手。
- **因子实验**：逐窗口训练与验证；可选 HistGradientBoosting。参数实验最多12组，共用冻结行情，验证期选参后只评估胜出配置的独立测试期。
- **模拟账户**：保留旧账与版本信息，新引擎不会默默推进旧版本账户。
- **数据与任务**：历史结果、取消、重试、快照重放、完整成交导出与结果分析。

旧策略标识和 API 路径继续保留，同构策略在目录中标为兼容别名。

## 数据与配置

`QUANT_DATA_LAKE_DIR` 指定已有行情库；未指定时优先使用仓库同级 `quant_data_lake`，再回退到后端目录。`DATA_LAKE_API_URL` 仍支持远程行情接口。原行情文件不进行破坏性迁移。

默认严格模式使用未复权成交价及显式公司行动重建指标；缺少必要数据时明确失败。复权价近似研究需要手动开启，结果带口径说明。日线无法恢复盘口、封单与盘中先后路径，相关撮合假设在结果中展示。

`QUANT_DATA_OFFLINE=1` 关闭行情提供方访问，只使用现有缓存。交易日历不足时诊断显示未验证，历史研究仍可按明确日期运行。新鲜度抽样不等于全市场已完整覆盖。

复制 `backend/.env.example` 了解配置项。服务密钥为 `QUANT_API_KEY`，模型密钥为 `QUANT_AI_MODEL_API_KEY`；旧 `QUANT_AI_API_KEY` 可暂作兼容回退。外部模型配置使用 `QUANT_AI_ENDPOINT`、`QUANT_AI_MODEL` 和 `QUANT_AI_OPENAI_COMPATIBLE`。结果助手默认本地分析，用户勾选后才调用外部模型；实验建议需要点击确认才能提交。

## 验证与迁移

```bash
cd backend
uv run --locked pytest -q
```

```bash
cd frontend
npm run api:check
npm run lint
npm test
npm run build
```

GitHub Actions 运行锁定安装、离线回归、前端检查与依赖审计。详见 [v3 接口、迁移和验收说明](docs/terminal-v3.md)。旧 v2 行为记录保留在 [Daily research v2](docs/reliable-research-v2.md)。
