# Factor Lab / ML 因子实验室使用说明

## 目标

Factor Lab 基于现有 A 股股票池与主回测链路，提供以下能力：

- 统一 OHLCV / amount / turn / 估值字段
- 自动生成候选因子与前瞻标签
- 单因子评估与多因子模型训练
- 研究结果落盘到 `results/quant-factor-mining/reports/factor_lab`
- 将 ML 排序策略直接注册到现有 `strategy_registry.py`
- 通过 FastAPI 与前端控制台查看结果并发起回测

## 后端入口

- 研究结果读取：`GET /api/factor-lab/results`
- 候选因子列表：`GET /api/factor-lab/factors`
- 触发研究：`POST /api/factor-lab/run`
- ML 策略回测：`POST /api/factor-lab/backtest`

### `POST /api/factor-lab/run` 示例

```json
{
  "start_date": "2023-01-01",
  "end_date": "2024-12-31",
  "pool": "core",
  "label": "next_5d_ret",
  "top_n": 3,
  "max_symbols": 5,
  "initial_capital": 1000000,
  "stop_loss": -0.08,
  "circuit_breaker": -0.15,
  "commission_rate": 0.0003,
  "stamp_tax_rate": 0.001,
  "slippage_rate": 0.0003
}
```

### `POST /api/factor-lab/backtest` 示例

```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "initial_capital": 1000000,
  "factor": "ml_factor_ranker",
  "pool": "core",
  "max_positions": 3,
  "weight_mode": "score",
  "stop_loss": -0.08,
  "circuit_breaker": -0.15,
  "commission_rate": 0.0003,
  "stamp_tax_rate": 0.001,
  "slippage_rate": 0.0003
}
```

## 研究产物

运行研究后会生成以下文件：

- `factor_ranking.csv`
- `feature_importance.csv`
- `model_metrics.csv`
- `bucket_returns.csv`
- `stability.csv`
- `latest_scores.csv`
- `latest_model.joblib`
- `training_sample_scored.csv`
- `research_report.md`
- `latest_summary.json`

默认目录：

- `results/quant-factor-mining/reports/factor_lab`

## 前端入口

前端导航新增 `Factor Lab` 入口，页面支持：

- 选择股票池、时间区间、预测标签、Top N、最大样本数
- 运行研究
- 读取最近一次研究结果
- 触发 ML 排序策略回测
- 查看因子排行榜、特征重要性、模型指标、分桶收益、稳定性摘要

## 命令

后端测试：

```bash
cd /Users/gdxj/quant-viz-backtest/backend
PYTHONPATH=/Users/gdxj/quant-viz-backtest/backend python3 -m pytest -q
```

前端构建：

```bash
cd /Users/gdxj/quant-viz-backtest/frontend
npm run build
```

## 当前范围与已知限制

- 当前 MVP 仅对 A 股池开放，`pool=etf` 会被后端拒绝。
- `ml_factor_ranker` 与 `ml_factor_filter` 已接入回测，但研究默认先在 `core` / `blackhorse` / `all` 范围内使用。
- `ai_ml` 与 `ai_ml_pro_plus` 仍然高度重复，后续建议做策略命名澄清或去重。
- `factor_turnover` 在旧多因子引擎中的语义仍偏向成交量而不是真实换手率，后续建议统一口径。
