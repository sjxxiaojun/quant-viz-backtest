# Daily research v2

Implemented 2026-10-11 on feature/momo-reliable-research-v2. Runtime remains local: FastAPI, React/Vite, SQLite, Parquet.

## Behavioral contracts

- Historical all-market samples are frozen from the 20 observed bars before start_date, ranked by median turnover with stable code tie breaks. Readable quarantined ST/delisted files participate. This is a fixed sample, not a certified survivorship-free universe. Explicit/current curated pools retain their retrospective limitation.
- Strict indicators use a causal total-return series reconstructed from raw bars and known actions, independent of a later qfq download base; the ledger uses raw_* prices. Approximate mode retains the legacy adjusted series. Default API price_mode=strict_raw. approximate_adjusted is explicitly a research approximation; allow_mock results receive the same caveat. Raw cache is independent of legacy files. Unknown strategies/weight modes/extra request fields are rejected.
- Ordinary signals execute at the next open. same_close_approximation=true opts into the registry's close-entry approximation for research only. V2 paper accounts always use next-open execution.
- Explicit company actions provide cash_dividend_per_share, dividend_pay_date, share_multiplier and share_available_date. Cash is a receivable until payout; distributed shares are unavailable until their listing date. Missing/unsupported actions, dates or fractional share compensation block strict execution. Gross cash dividends are recorded; differential dividend tax is not modeled. Daily volume and touched-limit fills remain declared approximations.
- Historical stock fees include effective-date transfer-fee segments across Shanghai/Shenzhen/Beijing, and existing segmented stamp tax. ETF/bond stamp/stock-transfer exemptions remain. Settlement days can be configured per instrument in runtime/raw/instruments.json; known 511/513/518 ETF families use T+0. Other ETFs default conservatively to T+1 and require per-instrument overrides for their actual settlement/limit rules.
- ML evaluation is causal-wf-v2: fixed 120 train / 40 validation / 20 prediction windows, every 20 bars. Each window selects candidate factors, fits clipping bounds, trains and chooses blend weights using only earlier labels. Labels crossing fit/validation boundaries are purged. Historical scores carry recipe_as_of. The latest model scores only dates after trained_through. Old manifests and approximate-price research artifacts are rejected for new paper execution. Approved versions validate their pinned artifact, independently of the mutable latest research run. A declared window budget can leave unpredicted tails; coverage is explicit.

## Local state and rollout

The original virtual_trading.db accounts/trades are preserved. An SQLite backup was taken before changes. QUANT_RUNTIME_DIR (default backend/runtime, ignored by git) holds:

- research_jobs.db: complete durable job requests/results, FIFO queue, two bounded subprocess slots, stage/error/state.
- virtual_v2.db: 1m-cash paper accounts, frozen universe, ledger state, lots, pending weights and policy state. Initial creation occurs only when the baseline date has complete raw data. Version switches archive the previous v2 account before creating a fresh account; old accounts are not replayed.
- snapshots/<sha256>.parquet and .json: canonical per-run market frame and request/universe manifest.
- raw/<code>.parquet: unadjusted OHLC/official reference data; raw/actions/<code>.json: BaoStock corporate actions.
- trade_calendar.json: verified exchange dates from the existing free provider. Missing calendar coverage fails closed. Shanghai time is used for scheduling. Expired intraday snapshots are not replayed after hours, and failed jobs remain retryable.

Historical jobs are not automatically purged. Delete/export retention policy is deliberately left to an explicit future user action; there is no background deletion of saved research. Factor Lab immutable archives retain the existing protected-reference cleanup policy.

## API and UI

Existing submit/status/result URLs remain. Added /api/research/jobs, /{job_id}, /{job_id}/result, /{job_id}/cancel, /{job_id}/trades, /{job_id}/trades.csv and /api/factor-lab/jobs. Completed results retain every trade. Comparisons/factor runs support complete trade export. Queue admission is bounded at 20 pending/running requests. Interrupted and canceled tasks cannot be overwritten by late success. Worker logs go to job_workers.log.

Virtual account reads accept version=v2 (default) or legacy. Execution updates only v2 accounts. Data diagnostics expose actual sampled cache dates, checked coverage, missing symbols and calendar errors. Readiness is not a claim that current data is complete.

Pages use #console?job=<id>, #compare?job=<id>, #factorLab?job=<id> and #tasks. Backtest/comparison recover saved jobs after refresh; research results are selectable from history, with cancel/resubmit, result comparison and full CSV export. Current account versions are explicitly selectable. Backtest parameters extend generated OpenAPI types; job views are generated directly. Run npm run api:types / api:check after API schema changes.

## Validation and practical limitations

- Full backend regression: 480 passed. Frontend: 9 interaction tests; lint/build and OpenAPI drift checks passed. npm audit: zero vulnerabilities after compatible dependency updates.
- New cases exercise future-liquidity/label perturbations, raw-vs-adjusted separation, shared ledger equality, T+0/T+1, corporate actions, restart/cancellation, two real subprocess slots, 600-trade pagination/export, official calendar holidays, daily account catch-up and missing-day stop.
- Frozen real cache: 000001 turtle, 2023-06-01..2024-12-31, 39 fills in approximate_adjusted mode. Baseline final value 1,090,823.95; v2 1,090,304.02; difference -519.93. Added Shenzhen transfer fees plus cash/lot rounding explain the change. This is an accounting comparison, not strict raw-price performance validation.
- Strict 518880 online-price verification was blocked by the Eastmoney connection/proxy failure. No adjusted prices were substituted. Restoring current-market operation requires reachable free data providers and complete raw/action/calendar coverage; old caches were not presented as current data.
- Original account and trade records match the backup. No live-broker connection is introduced.

Provider field reference: https://github.com/zxygithub/baostock/blob/master/docs/pythonAPI.md (query_dividend_data). 159915 effective limit reference: https://docs.static.szse.cn/www/aboutus/trends/conference/W020200821767425488573.pdf. ETF settlement reference: https://www.sse.com.cn/assortment/fund/etf/question/c/c_20240118_5734755.shtml.

## Starting

Use the existing backend launch script or backend/venv/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 8080, then npm run dev in frontend. QUANT_AUTOMATION_SCHEDULER_ENABLED=0 disables scheduling for isolated previews. QUANT_WARM_MARKET_CACHE=0 disables startup warming for diagnostics. Never run regression tests against production accounts: conftest.py and the OpenAPI generator isolate runtime/database files.
