# Factor Lab 测试准备与 ML 风险说明

## 本轮新增测试目标

本轮测试补位优先围绕四类契约，尽量不改主实现：

- 数据标准化：验证 `DataManager._normalize_market_frame()` 会统一日期、数值列、股票代码、重复日期去重，以及保留 `amplitude` 这类额外特征列。
- 数据标准化：验证 `factor_lab.data_prep.standardize_market_frame()` 已经具备更强的 ML 契约，会同时补齐 `turn` / `turnover_rate` 与 `amplitude`。
- 特征/标签：验证隔夜信号工厂会产出 ML 需要的特征列，并且在 `top_n` 截断后保留 `raw_signal` 与 `signal` 的区分，避免训练标签和执行标签混淆。
- 策略注册：验证 `StrategySpec` 元数据完整，并固定 `overnight*` 系列的 `signal_type` / `holding_policy` / `execution_mode`。
- API 响应：验证现有 `/api/strategies` 已返回行为元数据，并补上 `/api/factor-lab/results`、`/api/factor-lab/factors`、`/api/factor-lab/backtest` 的轻量契约测试。

## 已新增的测试文件

- `backend/test_factor_lab_data_contracts.py`
- `backend/test_factor_lab_feature_contracts.py`
- `backend/test_factor_lab_registry_api_contracts.py`

其中包含两类测试：

- 可运行测试：覆盖当前代码已经存在的行为，保证现在就能跑。
- `xfail` 契约：把已知缺口写进测试，不阻塞当前 CI，但会持续提示需要补齐的行为。

## 当前会影响 ML / Factor Lab 落地的风险

### 1. `overnight` 对 `amplitude` / `turnover_rate` 的列依赖已在统一标准化里补齐

- `signal_factory` 的 `overnight_balanced` / `overnight_ranked` / `overnight_quality` 会直接读取 `features["turnover_rate"]` 和 `features["amplitude"]`：`backend/strategies/signal_factory.py:83-118`
- 当前 `DataManager._normalize_market_frame()` 已统一补齐 `turnover_rate`、`amplitude`、`prev_close`、`intraday_ret`、`open_gap`，并且 `MOCK` 回退也会走同一标准化逻辑：`backend/data_manager.py`

影响：

- 统一列契约后，`overnight*` 和 `factor_lab` 不再依赖策略内部零散补字段。
- `MOCK` 数据现在可继续走研究/回测链路，但合成行情本身仍然不适合作为研究结论依据，只适合兜底。

### 2. `ai_ml` 与 `ai_ml_pro_plus` 在注册表里是高度重复的同构策略

- `ai_ml` 配置：`backend/strategy_registry.py:123-138`
- `ai_ml_pro_plus` 配置：`backend/strategy_registry.py:285-300`

两者当前的 `MultiFactorStrategy` 因子、权重、`top_n` 全部相同：

- `low_vol` 0.42
- `value` 0.22
- `turnover` 0.08
- `top_n=2`

影响：

- 这会让前端、API、报告、A/B 对比看起来像两个策略，实际上是同一条信号链路，后续做 ML 版本追踪、因子实验归因、模型注册时会造成版本噪音。
- 如果未来 `factor_lab` 需要“策略 key -> 特征集/标签集”映射，这种重复 key 会放大配置漂移和实验记录混乱。

### 3. `factor_turnover` 名称与实际计算口径不一致

- `factor_turnover()` 实际返回的是 `volume` 的滚动均值，而不是换手率：`backend/strategies/multi_factor_engine.py:27-29`

影响：

- 在 ML 场景里，“turnover” 通常是一个明确的特征名。如果训练管线把它当成真实换手率使用，会导致特征血缘错误、训练集/线上特征语义不一致。
- 这也解释了为什么注册表里把因子叫 `turnover`，但数据层并没有真正统一 `turnover_rate` 契约。

## 建议下一步

- 合并或重命名 `ai_ml` / `ai_ml_pro_plus`，避免同构策略继续扩散到报告、前端选项和实验记录里。
- 继续保持 `turn` / `turnover_rate` 双写兼容，但逐步把策略和研究代码统一迁移到 `turnover_rate`。
