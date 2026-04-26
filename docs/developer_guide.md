# datahaus Developer Guide

Technical reference for developing, extending, and maintaining the datahaus platform.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Architecture & Design Patterns](#2-architecture--design-patterns)
3. [Schema Design](#3-schema-design)
4. [Exchange Adapter System](#4-exchange-adapter-system)
5. [Adding a New Exchange](#5-adding-a-new-exchange)
6. [DAG Development](#6-dag-development)
7. [Reconciliation Engine](#7-reconciliation-engine)
8. [Alert Router](#8-alert-router)
9. [Soda Data Quality](#9-soda-data-quality)
10. [Testing Strategy](#10-testing-strategy)
11. [Local Development Setup](#11-local-development-setup)
12. [Code Conventions](#12-code-conventions)

---

## 1. Project Structure

```
datahaus/
├── compute/                    # Business logic (no I/O, no Airflow deps)
│   ├── __init__.py
│   ├── ingest_klines.py        # Legacy Phase 1 transform (preserved for tests)
│   ├── adapters/               # Exchange-specific adapters
│   │   ├── __init__.py         #   Re-exports all adapters
│   │   ├── base.py             #   ABC: ExchangeAdapter
│   │   ├── binance.py          #   Binance v3 klines
│   │   ├── bybit.py            #   Bybit v5 klines
│   │   └── okx.py              #   OKX v5 candles
│   └── reconciliation.py       # Cross-exchange spread detection (pure functions)
│
├── pipelines/                  # Airflow DAGs (orchestration layer)
│   ├── __init__.py
│   ├── binance_klines_1m.py    # Binance ETL DAG
│   ├── bybit_klines_1m.py     # Bybit ETL DAG
│   ├── okx_klines_1m.py       # OKX ETL DAG
│   └── reconciliation_dag.py  # Cross-exchange reconciliation DAG
│
├── warehouse/                  # Storage layer
│   ├── schema.sql              # DDL for curated.btc_ohlcv
│   └── datahaus.duckdb         # DuckDB database (gitignored)
│
├── observability/              # Monitoring & alerting
│   ├── alert_router.py         # Alert routing logic
│   ├── alerts/                 # Alert output (JSONL log)
│   │   └── .gitkeep
│   └── soda_checks/            # Soda Core check definitions
│       ├── configuration.yml   #   DuckDB connection config
│       ├── btc_ohlcv.yml       #   Global checks
│       ├── binance_ohlcv.yml   #   Binance-specific checks
│       ├── bybit_ohlcv.yml     #   Bybit-specific checks
│       └── okx_ohlcv.yml       #   OKX-specific checks
│
├── scripts/                    # Operational scripts
│   ├── chaos_freshness.py      # Pause DAGs (chaos injection)
│   ├── chaos_clear.py          # Un-pause DAGs (recovery)
│   ├── chaos_spread.py         # Inject/clean fake price anomaly
│   └── migrate_phase2.py       # Phase 1 → Phase 2 schema migration
│
├── tests/                      # pytest test suite
│   ├── __init__.py
│   ├── test_ingest.py          # Legacy Phase 1 transform tests
│   ├── test_adapters.py        # All 3 adapter transform tests
│   └── test_reconciliation.py  # Spread detection + summary tests
│
├── runbooks/                   # Incident response procedures
│   ├── RB-01-binance-freshness.md
│   ├── RB-02-bybit-freshness.md
│   ├── RB-03-okx-freshness.md
│   └── RB-04-spread-divergence.md
│
├── docs/                       # Documentation
├── Makefile                    # All operational targets
├── pyproject.toml              # Python project config + pytest config
├── .env.example                # Environment variable template
└── .gitignore                  # Git ignore rules
```

### Layer Separation

The codebase follows a strict layered architecture:

| Layer | Directory | Depends On | Rules |
|-------|-----------|-----------|-------|
| **Compute** | `compute/` | Nothing | Pure functions. No I/O, no Airflow, no DuckDB. |
| **Orchestration** | `pipelines/` | compute, warehouse | Airflow DAGs. Manages ETL lifecycle. |
| **Storage** | `warehouse/` | Nothing | DDL only. No logic. |
| **Observability** | `observability/` | Nothing | Soda configs + alert router. |
| **Scripts** | `scripts/` | Airflow API, DuckDB | Operational tooling. Not imported by pipelines. |

**Key rule:** `compute/` never imports from `pipelines/` or `observability/`. The DAGs import from compute, not the other way around.

---

## 2. Architecture & Design Patterns

### Adapter Pattern (Exchange Abstraction)

Each exchange implements the `ExchangeAdapter` ABC:

```python
class ExchangeAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...           # "binance", "bybit", "okx"

    @abstractmethod
    def fetch_raw(self, ...) -> list: ... # HTTP call to exchange API

    @abstractmethod
    def transform(self, raw) -> list[dict]: ...  # Raw → unified dict
```

This separates exchange-specific API details from the common ETL pattern. Each DAG follows the same `extract → transform → load` structure and only differs in which adapter it uses.

### Delete-Then-Insert Upsert

Instead of SQL MERGE (not supported in all DuckDB versions), we use:
```sql
DELETE FROM curated.btc_ohlcv WHERE exchange = ? AND open_time IN (?...)
INSERT INTO curated.btc_ohlcv VALUES (...)
```

This is safe because:
- SequentialExecutor prevents concurrent writes
- Each exchange only touches its own rows (`WHERE exchange = ?`)
- Idempotent: re-running with same data produces same result

### Pure Function Design

All business logic in `compute/` is pure:
- `transform()` methods take data in, return data out
- `detect_spread_anomalies()` takes rows, returns anomaly dicts
- No side effects, no database calls, no HTTP calls
- Easy to unit test with mock data

---

## 3. Schema Design

### Current Schema (Phase 2)

```sql
CREATE TABLE curated.btc_ohlcv (
    exchange        VARCHAR     NOT NULL,   -- PK part 1
    open_time       BIGINT      NOT NULL,   -- PK part 2 (Unix ms)
    open            DOUBLE      NOT NULL,
    high            DOUBLE      NOT NULL,
    low             DOUBLE      NOT NULL,
    close           DOUBLE      NOT NULL,
    volume          DOUBLE      NOT NULL,   -- Base asset volume
    close_time      BIGINT,                 -- Binance only
    quote_volume    DOUBLE,                 -- Binance + Bybit
    trade_count     INTEGER,                -- Binance only
    taker_buy_base_volume   DOUBLE,         -- Binance only
    taker_buy_quote_volume  DOUBLE,         -- Binance only
    confirm         BOOLEAN,                -- OKX only
    ingested_at     TIMESTAMP   NOT NULL,
    PRIMARY KEY (exchange, open_time)
);
```

### Design Decisions

**Unified table (not per-exchange tables):**
- Single-scan reconciliation queries — no JOINs needed
- `SELECT exchange, close FROM btc_ohlcv WHERE open_time = ?` returns all exchanges
- Adding a new exchange = just inserting rows, no DDL changes

**Nullable exchange-specific fields:**
- Binance provides 12 fields, Bybit provides 7, OKX provides 9
- Rather than inventing values (e.g. `trade_count = 0` for Bybit), we use NULL
- Soda checks validate that exchange-specific fields are NOT NULL only for the exchange that provides them

**open_time as BIGINT (Unix milliseconds):**
- Matches all exchange API formats natively
- No timezone ambiguity
- Efficient for range queries and GROUP BY

**ingested_at as TIMESTAMP:**
- UTC wall-clock time when the row was written
- Used by Soda freshness checks
- Distinguishes "when was this candle" (open_time) from "when did we get it" (ingested_at)

### Column Availability Matrix

| Column | Binance | Bybit | OKX |
|--------|---------|-------|-----|
| exchange | "binance" | "bybit" | "okx" |
| open_time | int | str→int | str→int |
| open, high, low, close | str→float | str→float | str→float |
| volume | str→float | str→float | str→float |
| close_time | int | NULL | NULL |
| quote_volume | str→float | turnover→float | volCcyQuote→float |
| trade_count | int | NULL | NULL |
| taker_buy_base_volume | str→float | NULL | NULL |
| taker_buy_quote_volume | str→float | NULL | NULL |
| confirm | NULL | NULL | "0"/"1"→bool |

---

## 4. Exchange Adapter System

### Base Class

`compute/adapters/base.py` defines the ABC:

```python
class ExchangeAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def fetch_raw(self, symbol, interval, limit) -> list[Any]: ...

    @abstractmethod
    def transform(self, raw_data: list[Any]) -> list[dict[str, Any]]: ...
```

### Adapter Implementations

#### BinanceAdapter (`compute/adapters/binance.py`)

- **API:** `https://api.binance.com/api/v3/klines`
- **Response:** List of 12-element lists, chronological order
- **Symbol format:** `BTCUSDT` (no separator)
- **Interval format:** `1m`
- **Response order:** Chronological (no reversal needed)
- **Unique fields:** close_time, trade_count, taker_buy_base/quote_volume

#### BybitAdapter (`compute/adapters/bybit.py`)

- **API:** `https://api.bybit.com/v5/market/kline`
- **Response:** `result.list` — list of 7-element string lists
- **Symbol format:** `BTCUSDT` (no separator)
- **Interval format:** `1` (just the number for minutes)
- **Response order:** Newest-first → **must reverse**
- **Extra params:** `category=spot`
- **Error handling:** Check `retCode != 0`
- **Unique fields:** turnover (maps to quote_volume)

#### OKXAdapter (`compute/adapters/okx.py`)

- **API:** `https://www.okx.com/api/v5/market/candles`
- **Response:** `data` — list of 9-element string lists
- **Symbol format:** `BTC-USDT` (hyphen separator)
- **Interval format:** `1m`
- **Response order:** Newest-first → **must reverse**
- **Error handling:** Check `code != "0"`
- **Unique fields:** confirm ("0"/"1" → boolean), volCcyQuote (maps to quote_volume)

### Unified Output Format

All adapters output the same dict structure:

```python
{
    "exchange": str,           # adapter.name
    "open_time": int,          # Unix ms
    "open": float,
    "high": float,
    "low": float,
    "close": float,
    "volume": float,           # base asset
    "close_time": int | None,
    "quote_volume": float | None,
    "trade_count": int | None,
    "taker_buy_base_volume": float | None,
    "taker_buy_quote_volume": float | None,
    "confirm": bool | None,
    "ingested_at": str,        # UTC ISO format
}
```

---

## 5. Adding a New Exchange

To add a new exchange (e.g. KuCoin), follow these steps:

### Step 1: Create the adapter

```python
# compute/adapters/kucoin.py
from compute.adapters.base import ExchangeAdapter

class KuCoinAdapter(ExchangeAdapter):
    @property
    def name(self) -> str:
        return "kucoin"

    def fetch_raw(self, symbol="BTC-USDT", interval="1min", limit=100):
        # GET https://api.kucoin.com/api/v1/market/candles
        # Parse response, handle errors, reverse if needed
        ...

    def transform(self, raw_data):
        # Map API fields to unified schema
        # Set None for unavailable fields
        ...
```

### Step 2: Register in `__init__.py`

```python
# compute/adapters/__init__.py
from compute.adapters.kucoin import KuCoinAdapter
__all__ = [..., "KuCoinAdapter"]
```

### Step 3: Create the DAG

Copy `pipelines/bybit_klines_1m.py` and change:
- DAG ID to `kucoin_klines_1m`
- Import to `KuCoinAdapter`
- Tags to include `kucoin`

### Step 4: Add Soda check

Create `observability/soda_checks/kucoin_ohlcv.yml`:
```yaml
filter btc_ohlcv [kucoin]:
  where: exchange = 'kucoin'

checks for btc_ohlcv [kucoin]:
  - freshness(ingested_at) < 10m
  - row_count > 0
  - duplicate_count(open_time) = 0
```

### Step 5: Add tests

Add `TestKuCoinAdapter` class in `tests/test_adapters.py` with sample data.

### Step 6: Update chaos scripts

Add `"kucoin": "kucoin_klines_1m"` to `DAG_IDS` in `chaos_freshness.py` and `chaos_clear.py`.

### Step 7: Add Makefile targets

```makefile
trigger-kucoin:
	@curl ... http://localhost:8080/api/v1/dags/kucoin_klines_1m/dagRuns ...
```

### Step 8: Add runbook

Create `runbooks/RB-0N-kucoin-freshness.md` based on existing templates.

### No schema changes needed

The unified table design means adding an exchange requires zero DDL changes. Just insert rows with `exchange='kucoin'`.

---

## 6. DAG Development

### DAG Template

All exchange DAGs follow this pattern:

```python
# Standard imports
from airflow import DAG
from airflow.operators.python import PythonOperator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_DB = PROJECT_ROOT / "warehouse" / "datahaus.duckdb"
SCHEMA_SQL = PROJECT_ROOT / "warehouse" / "schema.sql"

# DAG config
dag = DAG(
    dag_id="exchange_klines_1m",
    schedule_interval="*/5 * * * *",
    default_args={
        "retries": 3,
        "retry_delay": timedelta(minutes=1),
        "retry_exponential_backoff": True,
        "execution_timeout": timedelta(minutes=5),
    },
    catchup=False,
    max_active_runs=1,
)

# Task 1: Extract (API call)
def extract(**kwargs):
    sys.path.insert(0, str(PROJECT_ROOT))
    from compute.adapters.xxx import XXXAdapter
    adapter = XXXAdapter()
    data = adapter.fetch_raw()
    kwargs["ti"].xcom_push(key="raw_klines", value=json.dumps(data))

# Task 2: Transform (adapter.transform)
def transform(**kwargs):
    ...
    rows = adapter.transform(raw_data)
    kwargs["ti"].xcom_push(key="transformed_rows", value=json.dumps(rows))

# Task 3: Load (DuckDB upsert)
def load(**kwargs):
    ...
    # DELETE WHERE exchange = 'xxx' AND open_time IN (...)
    # INSERT rows

extract_task >> transform_task >> load_task
```

### Why `sys.path.insert`?

Airflow's SequentialExecutor runs tasks in subprocesses. The working directory isn't guaranteed to be the project root, so we explicitly add it to `sys.path` before importing from `compute/`.

### XCom Data Flow

```
extract  ──[XCom: raw_klines]──→  transform  ──[XCom: transformed_rows]──→  load
         (JSON string)                        (JSON string of dicts)
```

XCom stores data as JSON strings in Airflow's metadata DB (SQLite). For 100 candles this is ~20KB — well within limits.

---

## 7. Reconciliation Engine

### Core Algorithm (`compute/reconciliation.py`)

```python
def detect_spread_anomalies(rows, threshold=0.01):
    # 1. Group rows by open_time
    by_time = {open_time: {exchange: close_price, ...}, ...}

    # 2. For each timestamp, compare all exchange pairs
    for open_time, prices in by_time.items():
        for (exchange_a, exchange_b) in combinations(exchanges, 2):
            midpoint = (close_a + close_b) / 2
            spread = |close_a - close_b| / midpoint
            if spread > threshold:
                yield anomaly

    # Returns list of anomaly dicts
```

### Spread Calculation

Uses **midpoint-relative spread** (not percentage of either price):

```
spread = |price_a - price_b| / ((price_a + price_b) / 2)
```

This is symmetric — `spread(A,B) == spread(B,A)`.

### Threshold Tuning

| Threshold | Use Case |
|-----------|----------|
| 0.001 (0.1%) | Too noisy — normal market microstructure |
| 0.005 (0.5%) | Sensitive — catches significant divergence |
| **0.01 (1%)** | **Default — good balance for BTC on major exchanges** |
| 0.02 (2%) | Conservative — only extreme events |
| 0.05 (5%) | Used by chaos testing (`chaos_spread.py` injects +5%) |

---

## 8. Alert Router

### Architecture (`observability/alert_router.py`)

```python
def route_alert(check_name, table, exchange, outcome, details):
    record = {timestamp, check_name, table, exchange, outcome, details}

    # Always: append to JSONL file
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")

    # Optional: POST to Slack if SLACK_WEBHOOK_URL is set
    if os.environ.get("SLACK_WEBHOOK_URL"):
        requests.post(webhook_url, json=slack_msg)
```

### Design Principles

- **File sink is always active** — zero external dependencies
- **Slack is fail-open** — if the webhook call fails, it logs the error but doesn't break the pipeline
- **Structured records** — JSONL for easy grep, jq, and future ingestion
- **Idempotent alert routing** — calling route_alert twice appends two records (correct behavior)

### Configuring Slack

```bash
# Set the webhook URL
export SLACK_WEBHOOK_URL="<your-slack-webhook-url>"

# Or add to .env file
echo 'SLACK_WEBHOOK_URL=<your-slack-webhook-url>' >> .env
```

---

## 9. Soda Data Quality

### Check Architecture

```
configuration.yml          → DuckDB connection settings
btc_ohlcv.yml             → Global checks (all exchanges combined)
binance_ohlcv.yml          → Binance partition: freshness + NOT NULL
bybit_ohlcv.yml           → Bybit partition: freshness
okx_ohlcv.yml             → OKX partition: freshness + confirm
```

### Partition Filters

Soda supports `filter` blocks to scope checks to a subset of rows:

```yaml
filter btc_ohlcv [binance]:
  where: exchange = 'binance'

checks for btc_ohlcv [binance]:
  - freshness(ingested_at) < 10m    # only checks Binance rows
```

### Check Types Used

| Check | What It Does |
|-------|-------------|
| `freshness(col) < Nm` | MAX(col) must be within N minutes of now |
| `row_count > 0` | Table/partition must not be empty |
| `duplicate_count(cols) = 0` | No duplicate values for the given columns |
| `missing_count(col) = 0` | No NULL values in the column |

---

## 10. Testing Strategy

### Test Organization

```
tests/
├── test_ingest.py          # 5 tests — legacy Phase 1 transform
├── test_adapters.py        # 22 tests — all 3 adapter transforms
└── test_reconciliation.py  # 10 tests — spread detection + summary
```

**Total: 37 tests**

### What We Test

| Component | Test Type | Strategy |
|-----------|----------|----------|
| Adapter transforms | Unit | Mock raw API data → verify output dicts |
| Reconciliation | Unit | Constructed scenarios → verify anomaly detection |
| Summarize | Unit | Constructed anomalies → verify text output |

### What We Don't Test (and why)

| Component | Why Not Unit Tested |
|-----------|-------------------|
| `fetch_raw()` | Makes real HTTP calls — tested via integration (trigger DAG) |
| DAG load tasks | Requires DuckDB — tested via integration (trigger + db-query) |
| Alert router | Has side effects (file write, HTTP) — tested via chaos scenarios |
| Soda checks | Declarative YAML — tested by running `make run-checks-all` |

### Running Tests

```bash
# All tests
make test

# Specific test file
~/.venvs/datahaus/bin/python -m pytest tests/test_adapters.py -v

# Specific test class
~/.venvs/datahaus/bin/python -m pytest tests/test_adapters.py::TestBybitAdapter -v

# With coverage (if pytest-cov installed)
~/.venvs/datahaus/bin/python -m pytest tests/ -v --cov=compute
```

### Test Data Conventions

Each adapter test uses hardcoded sample data that mirrors the real API format:
- Binance: 2 candles, 12 fields each (list of lists, int/str mixed)
- Bybit: 2 candles, 7 fields each (list of string lists)
- OKX: 2 candles, 9 fields each (list of string lists, confirm "0"/"1")

---

## 11. Local Development Setup

### Prerequisites

- Ubuntu 22.04+ or WSL2
- Python 3.10+
- Java 17+ (for PySpark, if used)
- `make`

### First-Time Setup

```bash
# Clone and enter project
cd ~/datahaus

# Install everything
make setup          # creates venv, installs deps
make airflow-init   # init Airflow DB
make db-init        # create DuckDB schema

# Start Airflow (Terminal 1)
make airflow

# Trigger pipelines (Terminal 2)
make trigger-all
sleep 120
make db-query-all    # verify
make run-checks-all  # verify
make test            # run unit tests
```

### Development Workflow

```bash
# 1. Make code changes

# 2. Run unit tests
make test

# 3. If you changed a DAG: restart Airflow (Ctrl+C + make airflow)
#    Airflow auto-reloads DAG files, but restart is safest.

# 4. If you changed schema: run migration
make db-migrate

# 5. Trigger and verify
make trigger-all
sleep 120
make db-query-all
make run-checks-all
```

### Useful Development Commands

```bash
# Direct DuckDB SQL
~/.venvs/datahaus/bin/python -c "
import duckdb
con = duckdb.connect('warehouse/datahaus.duckdb')
print(con.execute('SELECT * FROM curated.btc_ohlcv LIMIT 5').fetchdf())
con.close()
"

# Test a single adapter interactively
~/.venvs/datahaus/bin/python -c "
from compute.adapters.bybit import BybitAdapter
a = BybitAdapter()
raw = a.fetch_raw(limit=5)
rows = a.transform(raw)
for r in rows:
    print(r['open_time'], r['close'], r['exchange'])
"

# Check Airflow DAG parsing errors
AIRFLOW_HOME=.airflow ~/.venvs/datahaus/bin/airflow dags list-import-errors
```

---

## 12. Code Conventions

### Python Style

- Python 3.10+ (`from __future__ import annotations`)
- No type stubs — inline type hints in signatures
- `logging` module for all log output (no `print()` in library code)
- `pathlib.Path` for all file paths

### Naming

| Item | Convention | Example |
|------|-----------|---------|
| Exchange adapter | `{Exchange}Adapter` | `BybitAdapter` |
| DAG ID | `{exchange}_klines_1m` | `bybit_klines_1m` |
| DAG file | `{exchange}_klines_1m.py` | `bybit_klines_1m.py` |
| Soda check file | `{exchange}_ohlcv.yml` | `bybit_ohlcv.yml` |
| Runbook | `RB-{NN}-{exchange}-{issue}.md` | `RB-02-bybit-freshness.md` |
| Exchange name (data) | lowercase | `"bybit"` |

### Imports

```python
# Standard library
from __future__ import annotations
import json
import logging

# Third party
import duckdb
import requests
from airflow import DAG

# Local
from compute.adapters.binance import BinanceAdapter
from compute.reconciliation import detect_spread_anomalies
```

### Error Handling

- Adapters raise `RuntimeError` on API error codes
- Airflow retries handle transient failures
- Alert router catches Slack errors (fail-open)
- No bare `except:` — always catch specific exceptions
