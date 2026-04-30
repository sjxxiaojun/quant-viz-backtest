# Backtest Exit Semantics Design

Date: 2026-04-22
Project: quant-viz-backtest
Scope: Fix exit semantics, unify risk exits, and add deterministic regression coverage

## Goal

Repair the backtest framework so that:

- event-driven strategies do not become accidental long-hold strategies
- ranking strategies sell names that drop out of the selected set
- stateful strategies keep their existing `1/-1/0` semantics
- stop-loss and take-profit exits cannot be immediately bought back on the same day
- trade statistics count all closed trades, not only normal sells

This is a phase-1 architecture repair. It should fix the current P0/P1 issues while preserving a path to a fuller lifecycle framework later.

## Current Failure Chain

The current API path is:

1. `main.py` loads data and applies a strategy function to produce `signal` and optional `score`
2. `position_manager.py` interprets those signals into holdings
3. `engine.py` executes yesterday's target weights at today's open

The key fault is that a single holding interpreter is reused for incompatible strategy types:

- event-driven strategies need timeout-based or selection-based exits
- ranking strategies should hold only the currently selected names
- stateful strategies can keep the existing `1 => enter`, `-1 => exit`, `0 => hold` behavior

Because all three are forced through one `PositionManager`, `signal == 0` is currently treated as "keep holding", which freezes positions across multiple strategy families.

## Design

## 1. Strategy Catalog

Add a `StrategySpec` structure in `strategy_registry.py` with:

- `key`
- `name`
- `func`
- `pool`
- `category`
- `signal_type`: `event`, `ranking`, or `stateful`
- `holding_policy`: `timeout_exit`, `hold_while_selected`, or `sell_on_minus_one`
- `default_max_hold_days`
- `default_take_profit`

The registry remains the source of truth for strategy metadata and for selecting the correct portfolio policy.

Initial classification:

- `event`: `overnight`, `weak_to_strong`, `limit_up_doji`, `aph_pro`
- `ranking`: `sector_alpha`, `ai_ml`, `ai_ml_pro`, `ai_ml_pro_plus`, `bottom_fishing`, `bottom_fishing_stable`, `ai_adaptive_pro`, `ai_adaptive_pro_plus`, `blackhorse_pro`, `blackhorse_pro_plus`
- `stateful`: `atm`, `reversal`, `turtle`, `hfmr`, `blackhorse`, `ai_adaptive`

Default event timeout assumption for this repair:

- `overnight`: 1
- `weak_to_strong`: 1
- `limit_up_doji`: 1
- `aph_pro`: 1

This keeps event strategies from sticking indefinitely and can be tuned later without changing the framework contract.

## 2. Portfolio Policy Layer

Replace the single holding interpretation with policy-driven logic in `position_manager.py`.

Policies:

- `EventPolicy`
  - source of truth is the signal date tracked by the policy
  - explicit `-1` exits immediately remove a name from tomorrow's target
  - positive signals add names
  - names expire by `max_hold_days`
  - this fixes "signal 0 means hold forever" for event strategies

- `RankingPolicy`
  - tomorrow's target set is the set of names with `signal == 1` today
  - if a name drops out of the selected set, it must be sold on the next rebalance
  - this fixes frozen positions in ranking strategies where names fall out of top-N but are not bottom-N

- `StatefulPolicy`
  - keep existing semantics
  - `1` adds, `-1` removes, `0` holds
  - still respects optional `max_hold_days`

`PositionManager` becomes a thin facade that picks the correct policy from `StrategySpec`.

## 3. Engine Contract and Risk Exits

`engine.py` continues to accept a full-target weight dict, but the contract becomes explicit:

- signal callbacks must return the complete target portfolio for the next open
- `engine.py` should not infer strategy semantics

Add unified risk exits:

- `stock_stop_loss`
- `stock_take_profit`
- `portfolio_circuit_breaker`

Add a same-day reentry block:

- if a position exits via `stop_loss` or `take_profit` at today's open, that code cannot be bought again during the same day's rebalance

Closed-trade statistics must count exits with side:

- `sell`
- `stop_loss`
- `take_profit`
- `circuit_break`

## 4. API and Request Handling

`main.py` should:

- resolve `StrategySpec`
- use strategy defaults when request-level `max_hold_days` or `take_profit` are absent
- construct `PositionManager` with strategy behavior
- pass current positions into the signal callback so policies can stay aligned with actual holdings after risk exits

The external API remains backward compatible. New request field:

- `take_profit`

## 5. Validation

Add deterministic regression tests using handcrafted daily bars:

1. `Exit-01`: empty target exits on the next open
2. `Overnight-01`: one-night hold is enforced
3. `StopLoss-01`: stop-loss cannot buy back the same code on the same day
4. `Stats-01`: closed-trade statistics count stop-loss and normal sells consistently

Keep a lightweight smoke path for longer samples after deterministic tests pass.

## Error Handling

- If a strategy has unsupported metadata, fail loudly during setup instead of silently falling back
- If no eligible target names exist for a ranking or event policy, return an empty target dict
- If signal callbacks do not accept current positions, the engine should fall back to the legacy two-argument call path for compatibility

## Out of Scope

- multi-leg exits
- partial profit-taking
- per-strategy custom cooldown windows
- portfolio optimizer redesign
- refactoring the FastAPI routes into a dedicated application service layer

## Implementation Order

1. add `StrategySpec` metadata
2. refactor `position_manager.py` into policy-driven semantics
3. add `take_profit`, same-day reentry blocking, and corrected statistics in `engine.py`
4. wire request defaults and signal callback context in `main.py`
5. add deterministic regression tests
6. update the overnight verification script to use the same semantics as the API path

## Self-Review

- No placeholders remain
- The design stays within one implementation pass
- Exit semantics are explicit for all current strategy families
- Validation includes the exact four failure classes reported by the user
