# Trading Engine

Paper-trading engine for InvestoryX. This module will run scheduled jobs that fetch prices, evaluate strategies, and execute simulated trades against portfolios.

## Goals
- Paper-trading only (no brokerage integration)
- Strategy-driven decisions (buy/sell/hold)
- Clear job pipeline with auditability
- Easy to extend with new strategies or execution rules

## High-Level Flow
1. Fetch price data (daily open/close)
2. Evaluate strategies and generate signals
3. Execute paper trades based on signals
4. Reconcile portfolio state and performance

The daily run (`tasks/daily_pipeline.py`) executes these as fetch → execute →
reconcile → evaluate: a signal decided on day D's close fills at day D+1's open,
so each run first fills the previous trading day's signals, then evaluates the
new close. Backtests (`services/backtest.py`) simulate every day the same way and
size orders with the same `plan_fill()` and `ExecutionRules` as live execution.

### 1. Fetch Price Data (Daily Open/Close)
- Purpose: Build reliable market data inputs before any strategy decision is made.
- What happens:
  - Load the list of tracked symbols for active simulators.
  - Pull daily bars (open/high/low/close/volume) from the configured data provider.
  - Upsert bars into `price_bars` so reruns are idempotent.
- Input:
  - Symbol list (or all enabled tracked symbols)
  - Trading day/date range
- Output:
  - Fresh `price_bars` records used by strategy evaluation.
- Business rule:
  - No prices means no trustworthy decisions; downstream steps should skip/fail clearly rather than guessing.

### 2. Evaluate Strategies and Generate Signals
- Purpose: Convert market data + current portfolio context into explicit decisions.
- What happens:
  - Load each simulator's strategy and its saved params (`simulators.strategy_params`,
    validated by the models in `strategies/params.py`; `strategies/catalog.py` lists
    every strategy).
  - Build a portfolio snapshot (cash + current positions).
  - Run strategy logic against recent prices.
  - Persist one signal per decision (`buy`, `sell`, or `hold`) with reason/confidence.
- Input:
  - Price history
  - Portfolio snapshot
  - Strategy parameters (for example SMA windows, trade size)
- Output:
  - `simulator_signals` rows with `pending` execution status.
- Business rule:
  - Strategies decide intent only; they do not move cash or shares directly.

### 3. Execute Paper Trades Based on Signals
- Purpose: Turn valid executable signals into simulated fills and immutable trade records.
- What happens:
  - Read `pending` signals in deterministic order.
  - Validate each signal; only signals from the previous trading day are due, and
    they fill at the trade day's open (older ones expire).
  - Size each order with `plan_fill()`: fees, slippage, and risk caps
    (`max_position_pct` per simulator, `SIM_MAX_ORDER_VALUE` platform-wide) shrink
    buys to the whole shares that fit.
  - Apply execution/risk checks (cash available, shares available, positive quantity).
  - Create `simulator_trades` rows for executed signals and mark signal status (`executed`, `skipped`, or `failed`).
- Input:
  - Pending signals
  - Latest market price per symbol
  - Current simulator cash/holdings and execution settings (fee/slippage)
- Output:
  - Executed trade ledger entries and updated signal statuses.
- Business rule:
  - Trade ledger is the source of truth for what actually happened in simulation.

### 4. Reconcile Portfolio State and Performance
- Purpose: Ensure derived state (cash and positions) matches the trade ledger and compute portfolio results.
- What happens:
  - Replay executed trades in order for each simulator.
  - Recompute canonical cash balance and per-symbol position state (shares, average cost).
  - Update `simulators.cash_balance` and `simulator_positions` to match computed truth.
  - Optionally compute performance metrics (equity, P/L, return) from positions + latest prices.
- Input:
  - Executed trade ledger
  - Existing portfolio state
  - Latest prices (for mark-to-market valuation)
- Output:
  - Reconciled portfolio state and performance numbers.
- Business rule:
  - If stored cash/positions drift from replayed trades, reconciliation corrects drift and restores consistency.

## Manual Trading
- A simulator whose strategy is `manual` (`strategies/manual.py`) is traded by hand.
  Evaluation skips it, so the bot never trades it; switching the strategy back and
  forth is how a simulator moves between manual and automated trading.
- `services/manual_orders.py` handles market orders (whole shares):
  - Market open: fills immediately at Yahoo's latest price.
  - Market closed: saved to `simulator_orders` and filled at the next trading day's
    open by `tasks/fill_queued_orders.py` (every 15 minutes during the session, and
    again in the daily pipeline as a fallback). Pending buys set aside cash, and
    pending sells set aside shares, so queued orders can't overcommit.
  - Every fill goes through `plan_fill()`, so fees and slippage match the bot. A
    risk limit rejects the order instead of shrinking it, and the message says how
    many shares fit.
- Trades are tagged `source='manual'` and replayed by reconciliation like live trades.
- Switching to manual cancels the strategy's pending signals; switching away cancels
  pending manual orders.
- API: `POST /api/simulator/{id}/orders/quote` prices an order for the confirm step,
  `POST /api/simulator/{id}/orders` places it, and `DELETE /api/simulator/{id}/orders/{order_id}`
  cancels a queued one.

## Folders
- `tasks`: Celery task definitions (price fetch, strategy eval, execution, reconciliation)
- `strategies`: Strategy interfaces and implementations
- `models`: Data models and schema abstractions
- `services`: Shared services (data access, pricing, execution, risk rules)
- `schedules`: Celery Beat schedule definitions

## Folder Responsibilities (Detailed)
- `tasks`
  Purpose: Celery task entrypoints and orchestration.
  Notes: Keep tasks thin; delegate logic to services and strategies.
- `strategies`
  Purpose: Strategy interface and concrete implementations.
  Notes: Strategies should be pure and testable without Celery or DB context.
- `models`
  Purpose: Portfolio, position, order, trade, price bar, and signal models.
  Notes: Align with the backend ORM and persistence layer.
- `services`
  Purpose: Business logic for pricing, execution, portfolio updates, and risk rules.
  Notes: Avoid Celery-specific imports; keep services reusable.
- `schedules`
  Purpose: Centralized Celery Beat schedule definitions.
  Notes: Keep cadence and task ordering here to avoid scattering schedule logic.

## Scheduling
- Use Celery Beat to trigger daily jobs (e.g., after market close)
- Keep scheduling config centralized in `schedules`
- `run_daily_pipeline` executes `fetch_prices` -> `evaluate_strategies` -> `execute_paper_trades` -> `reconcile_portfolios` in order inside one task, so ordering never depends on timing or worker concurrency
- Every stage works on one trading day (`last_completed_trading_day()`, NYSE holidays excluded); evaluation skips symbols without a bar for that day and simulators already evaluated for it, and execution only fills at that day's close
- Backtest trades (`source='backtest'`) are never replayed into live portfolios; backtests do not change `simulators.cash_balance`
- `POST /api/simulator/{id}/run` runs the same pipeline scoped to one simulator

## Notes
- This module is intentionally framework-agnostic for now and will be wired into the main backend once the pipeline is defined.
