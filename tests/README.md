# Tests

A small suite: end-to-end tests for the essential flows, plus unit tests for
isolated trading-engine logic. Mostly happy paths.

- `trading_engine/test_simulator_flow.py` — end to end: create a simulator, set
  its strategy, add a stock, run two days, check the next-open fill and portfolio.
- `api/` — end to end: register, login/refresh/logout, stock lookup.
- `trading_engine/services/` — unit: fill rules, portfolio replay, strategies,
  strategy params, trading calendar, backtest.
- `services/test_cache.py` — unit: market-data cache.

## Prerequisites

From the `investoryX-backend` root:

```bash
poetry install
poetry add --group dev pytest
```

## Run All Trading Engine Tests

```bash
poetry run pytest tests/trading_engine
```

## Run All Tests

```bash
poetry run pytest tests
```

## Run One Test File

```bash
poetry run pytest tests/trading_engine/test_simulator_flow.py
```

## Run One Test Function

```bash
poetry run pytest tests/trading_engine/services/test_execution_rules.py -k test_max_position_pct_shrinks_buy_to_whole_shares
```

## Optional PowerShell Shortcut

Add this to your PowerShell profile:

```powershell
function te-tests { poetry run pytest tests/trading_engine }
```

Then run:

```powershell
te-tests
```
