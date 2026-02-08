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

## Notes
- This module is intentionally framework-agnostic for now and will be wired into the main backend once the pipeline is defined.
