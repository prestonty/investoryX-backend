# Tests

This folder contains backend test suites, including trading engine unit tests.

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
poetry run pytest tests/trading_engine/tasks/test_execute_paper_trades.py
```

## Run One Test Function

```bash
poetry run pytest tests/trading_engine/tasks/test_execute_paper_trades.py -k test_record_paper_trades_returns_json_safe_dict
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
