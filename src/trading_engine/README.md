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
  - Load each simulator's strategy configuration and tunable params.
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
  - Validate each signal and load latest reference price.
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
- Execute pipeline tasks in this order: `fetch_prices` -> `evaluate_strategies` -> `execute_paper_trades` -> `reconcile_portfolios`
- Keep a small time gap between each scheduled step to reduce overlap risk and preserve deterministic state transitions

## Notes
- This module is intentionally framework-agnostic for now and will be wired into the main backend once the pipeline is defined.
