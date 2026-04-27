# datahaus — Process Flow Cheatsheet

> **One-liner:** A 24/7 multi-exchange crypto data pipeline that proves you can
> *operate* a data platform, not just build one.

---

## The Big Picture

```
 BINANCE API     BYBIT API      OKX API         <- 3 free public REST APIs
      |               |              |
      v               v              v
 [Adapter]       [Adapter]      [Adapter]        <- ABC pattern, normalize to unified schema
      |               |              |
      v               v              v
 [Airflow DAG]   [Airflow DAG]  [Airflow DAG]   <- 1 DAG per exchange, */5 cron
      |               |              |
      +-------+-------+-------+-----+
              |                |
              v                v
     DuckDB curated.btc_ohlcv               <- single table, composite PK (exchange, open_time)
              |                |
    +---------+--------+      |
    |                  |      |
    v                  v      v
 [Soda Checks]   [Reconciliation DAG]       <- 2 parallel observability paths
    |                  |
    v                  v
 freshness/nulls   spread detection          <- declarative YAML vs pure-function Python
    |                  |
    +--------+---------+
             |
             v
      [Alert Router]                         <- always JSONL, optionally Slack
             |
             v
    alert_log.jsonl + Slack
```

---

## Layer 1 — External Sources

**What:** Three public crypto REST APIs providing BTC/USDT 1-minute OHLCV candles.

**Why three exchanges:** Not because crypto matters. Three independent sources of the
same metric creates real reconciliation problems — the same pattern you'd see
reconciling data from multiple vendors at any financial institution.

| Exchange | Endpoint | Response Shape |
|----------|----------|----------------|
| Binance | `GET /api/v3/klines` | Array of 12-element arrays (chronological) |
| Bybit | `GET /v5/market/kline` | `result.list` of 7-element arrays (**newest-first**) |
| OKX | `GET /v5/market/candles` | `data` array of 9-element arrays (**newest-first**) |

**Key detail:** Bybit and OKX return newest-first. Adapters reverse them before transform.

---

## Layer 2 — Adapters (compute/adapters/)

**What:** An ABC + 3 concrete implementations. One class per exchange. Each knows
how to fetch raw data and normalize it to the unified schema.

### The Contract

```
compute/adapters/base.py  ->  ExchangeAdapter (ABC)
  .name         -> str           "binance" | "bybit" | "okx"
  .fetch_raw()  -> list[Any]     raw API response
  .transform()  -> list[dict]    unified row dicts
```

### Minimum output fields (from base.py docstring)

```
REQUIRED:  exchange, open_time, open, high, low, close, volume, ingested_at
NULLABLE:  close_time, quote_volume, trade_count,
           taker_buy_base_volume, taker_buy_quote_volume, confirm
           (set to None if exchange doesn't provide them)
```

### What each adapter does differently

| | Binance | Bybit | OKX |
|---|---------|-------|-----|
| **File** | `compute/adapters/binance.py` | `compute/adapters/bybit.py` | `compute/adapters/okx.py` |
| **URL constant** | `BINANCE_KLINES_URL` | `BYBIT_KLINES_URL` | `OKX_CANDLES_URL` |
| **Raw columns** | 12 (indices 0-11) | 7 (indices 0-6) | 9 (indices 0-8) |
| **Reversal** | No (already chronological) | Yes (`result.list` is newest-first) | Yes (`data` is newest-first) |
| **Unique fields populated** | `close_time`, `quote_volume`, `trade_count`, `taker_buy_base_volume`, `taker_buy_quote_volume` | `quote_volume` (from `turnover`) | `confirm` (from candle[8]) |
| **Fields set to None** | `confirm` | `close_time`, `trade_count`, `taker_buy_*`, `confirm` | `close_time`, `trade_count`, `taker_buy_*` |

### How to trace: adapter.transform()

```
Raw API array (e.g. Binance [1714000000000, "50000.0", ...])
  -> Map indices to named fields (OPEN_TIME=0, OPEN=1, HIGH=2, ...)
  -> Cast strings to float/int
  -> Set exchange = self.name ("binance")
  -> Set ingested_at = datetime.now(UTC).isoformat()
  -> Set exchange-specific nullable fields
  -> Return dict matching curated.btc_ohlcv columns
```

---

## Layer 3 — Airflow DAGs (pipelines/)

**What:** 4 DAGs total. 3 ingestion DAGs (one per exchange) + 1 reconciliation DAG.

### Ingestion DAGs (identical structure x3)

| DAG | File | Schedule | Adapter |
|-----|------|----------|---------|
| `binance_klines_1m` | `pipelines/binance_klines_1m.py` | `*/5 * * * *` | `BinanceAdapter` |
| `bybit_klines_1m` | `pipelines/bybit_klines_1m.py` | `*/5 * * * *` | `BybitAdapter` |
| `okx_klines_1m` | `pipelines/okx_klines_1m.py` | `*/5 * * * *` | `OKXAdapter` |

Each has 3 tasks chained: `extract >> transform >> load`

#### Task: extract()
```
1. Instantiate adapter (e.g. BinanceAdapter())
2. Call adapter.fetch_raw(symbol="BTCUSDT", interval="1m", limit=100)
3. json.dumps(raw) -> XCom push key="raw_klines"
```

#### Task: transform()
```
1. XCom pull key="raw_klines" -> json.loads()
2. Call adapter.transform(raw_data)
3. json.dumps(rows) -> XCom push key="transformed_rows"
```

#### Task: load()
```
1. XCom pull key="transformed_rows" -> json.loads()
2. Open DuckDB connection to warehouse/datahaus.duckdb
3. Execute schema DDL from warehouse/schema.sql (idempotent CREATE IF NOT EXISTS)
4. UPSERT strategy:
   a. Collect all open_time values from incoming rows
   b. DELETE FROM curated.btc_ohlcv WHERE exchange='X' AND open_time IN (...)
   c. INSERT each row with all 14 columns (parameterized ? placeholders)
5. Log total row count for this exchange
6. Close connection
```

**Why upsert (delete + insert)?** Handles late corrections from exchange APIs. If an
exchange re-publishes a candle for the same timestamp, we pick up the corrected values.

### Reconciliation DAG

| | |
|---|---|
| **DAG** | `reconciliation_dag` |
| **File** | `pipelines/reconciliation_dag.py` |
| **Schedule** | `*/5 2-57 * * *` (offset from ingestion to ensure fresh data) |
| **Task** | Single task: `reconcile()` |

#### Task: reconcile()
```
1. Open DuckDB in READ-ONLY mode
2. Query: SELECT exchange, open_time, close
         FROM curated.btc_ohlcv
         WHERE open_time >= (now_epoch_ms - 600,000)    <- last 10 minutes
3. Close DB connection
4. Convert raw tuples to list of dicts
5. Call detect_spread_anomalies(row_dicts)
6. Call summarize_anomalies(anomalies)
7. If anomalies found:
     route_alert(outcome="FAIL", details=summary)
   Else:
     route_alert(outcome="PASS", details="No spread anomalies detected.")
```

**Critical detail:** Every reconciliation run writes an alert record, PASS or FAIL.
This creates a complete audit trail — you can prove the system was checking even when
nothing was wrong.

---

## Layer 4 — Storage (warehouse/)

### Schema: `curated.btc_ohlcv`

```sql
CREATE TABLE curated.btc_ohlcv (
    exchange        VARCHAR   NOT NULL,    -- 'binance' | 'bybit' | 'okx'
    open_time       BIGINT    NOT NULL,    -- Unix ms, candle open
    open            DOUBLE    NOT NULL,
    high            DOUBLE    NOT NULL,
    low             DOUBLE    NOT NULL,
    close           DOUBLE    NOT NULL,
    volume          DOUBLE    NOT NULL,    -- Base asset volume
    close_time      BIGINT,               -- Binance only
    quote_volume    DOUBLE,               -- Binance & Bybit (turnover)
    trade_count     INTEGER,              -- Binance only
    taker_buy_base_volume   DOUBLE,       -- Binance only
    taker_buy_quote_volume  DOUBLE,       -- Binance only
    confirm         BOOLEAN,              -- OKX only
    ingested_at     TIMESTAMP NOT NULL,   -- UTC ingestion time
    PRIMARY KEY (exchange, open_time)
);
```

### Why this design

| Decision | Why |
|----------|-----|
| **Single table, not one per exchange** | Reconciliation is a single scan with no JOINs. `GROUP BY open_time` gives you all exchanges in one pass. |
| **Nullable exchange-specific columns** | Avoids lowest-common-denominator loss. Binance gives you 12 fields — keep them. OKX gives `confirm` — keep it. |
| **Composite PK (exchange, open_time)** | Natural key. One candle per exchange per minute. No surrogate needed. |
| **DuckDB, not Postgres** | Zero-ops: single file, no server, no connection pooling, no pg_hba.conf. Columnar storage is fast for OLAP queries. |
| **BIGINT for timestamps** | Exchange APIs return Unix milliseconds. Storing as-is avoids conversion errors and timezone bugs. |

### Where the file lives

```
warehouse/datahaus.duckdb    <- created at first load(), grows with data
warehouse/schema.sql         <- DDL source, executed idempotently by every load()
```

---

## Layer 5a — Observability: Soda Checks

**What:** Declarative YAML rules that validate data quality. Run independently
from DAGs via `make soda`.

### Check files

| File | Scope | Checks |
|------|-------|--------|
| `observability/soda_checks/btc_ohlcv.yml` | Entire table | `row_count > 0`, `duplicate_count(exchange, open_time) = 0` |
| `observability/soda_checks/binance_ohlcv.yml` | `WHERE exchange = 'binance'` | freshness < 10m, row_count > 0, duplicate_count = 0, **5 missing_count checks** (close_time, quote_volume, trade_count, taker_buy_*) |
| `observability/soda_checks/bybit_ohlcv.yml` | `WHERE exchange = 'bybit'` | freshness < 10m, row_count > 0, duplicate_count = 0 |
| `observability/soda_checks/okx_ohlcv.yml` | `WHERE exchange = 'okx'` | freshness < 10m, row_count > 0, duplicate_count = 0, missing_count(confirm) = 0 |

### How Soda partitions checks

Soda uses **filter blocks** on a shared table:
```yaml
filter btc_ohlcv [binance]:
  where: exchange = 'binance'
```

This means each exchange gets its own freshness/quality evaluation without
needing separate physical tables.

### Configuration

```yaml
# observability/soda_checks/configuration.yml
data_source datahaus:
  type: duckdb
  path: warehouse/datahaus.duckdb   # relative — must run from project root
  schema: curated
```

---

## Layer 5b — Observability: Reconciliation Engine

**What:** Pure-function Python that detects when exchanges disagree on price.

### compute/reconciliation.py

#### `detect_spread_anomalies(rows, threshold=0.01)`

```
Input:  list of dicts, each with {exchange, open_time, close}
Output: list of anomaly dicts

Algorithm:
  1. Group rows by open_time -> dict[time -> dict[exchange -> close_price]]
  2. For each timestamp, get sorted list of exchanges present
  3. Compare every pair (N choose 2):
     - midpoint = (close_a + close_b) / 2
     - spread = |close_a - close_b| / midpoint
     - If spread > threshold (default 1%): record anomaly
  4. Return all anomalies with:
     {open_time, exchange_a, exchange_b, close_a, close_b, spread_pct, threshold}
```

**Why pure function?** No I/O, no database, no side effects. The DAG handles all I/O
(query DB, call alert router). The function is trivially unit-testable.

#### `summarize_anomalies(anomalies)`

Formats the anomaly list into human-readable text for the alert router.

---

## Layer 5c — Alert Router

**What:** Single function that is the system's only exit point for alerts.

### observability/alert_router.py

#### `route_alert(check_name, table, exchange, outcome, details)`

```
Always:
  1. Build record dict with timestamp, check_name, table, exchange, outcome, details
  2. Append JSON line to observability/alerts/alert_log.jsonl

If SLACK_WEBHOOK_URL env var is set:
  3. Map outcome to icon: PASS->check, FAIL->siren, WARN->warning
  4. POST formatted Slack message
  5. If Slack POST fails: log error, do NOT fail the caller (non-fatal)

Return: the alert record dict
```

**Output file:** `observability/alerts/alert_log.jsonl`

**Sample record:**
```json
{
  "timestamp": "2026-04-28T05:35:00.000000+00:00",
  "check_name": "spread_anomaly",
  "table": "curated.btc_ohlcv",
  "exchange": "cross-exchange",
  "outcome": "FAIL",
  "details": "Spread anomaly: binance vs okx at 1714000000000 — 2.4%"
}
```

---

## Layer 6 — Chaos Engineering (scripts/)

**What:** First-class chaos injection tools that prove the observability layer works.

### Two distinct failure modes

| Script | Failure Mode | What It Does | What It Triggers |
|--------|-------------|--------------|------------------|
| `scripts/chaos_freshness.py` | **Stale data** | Pauses an Airflow DAG via REST API (`PATCH is_paused=true`) | Soda freshness check fails (ingested_at > 10 min ago) |
| `scripts/chaos_spread.py` | **Price divergence** | Inserts fake row with `exchange='chaos_test'` and `close = real_close * 1.05` | Reconciliation DAG detects >1% spread, fires FAIL alert |

### chaos_freshness.py flow

```
1. Takes --exchange flag (binance|bybit|okx|all)
2. HTTP PATCH to http://localhost:8080/api/v1/dags/{dag_id}
   Body: {"is_paused": true}
3. DAG stops running -> no new rows -> ingested_at ages
4. Next Soda run: freshness(ingested_at) < 10m FAILS
```

### chaos_spread.py flow

```
1. --inject mode:
   a. Query latest open_time and close from curated.btc_ohlcv
   b. INSERT row with exchange='chaos_test', close = close * 1.05
2. Next reconciliation DAG run:
   a. Queries last 10 min (picks up fake row)
   b. detect_spread_anomalies() finds >1% spread
   c. route_alert(outcome="FAIL") fires
3. --clean mode:
   a. DELETE FROM curated.btc_ohlcv WHERE exchange='chaos_test'
```

### chaos_clear.py

Reverses `chaos_freshness.py`: unpauses the DAG (`is_paused=false`).

---

## Trace: Follow a Single Candle

Here is the complete journey of one BTC/USDT candle from Binance:

```
T+0s    Airflow scheduler triggers binance_klines_1m DAG

T+1s    extract() runs:
          BinanceAdapter().fetch_raw("BTCUSDT", "1m", 100)
          -> HTTP GET https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=100
          -> Returns: [[1714000000000, "94250.50", "94300.00", "94200.00", "94275.00", "12.5", ...], ...]
          -> json.dumps() -> XCom push "raw_klines"

T+3s    transform() runs:
          XCom pull "raw_klines" -> json.loads()
          BinanceAdapter().transform(raw_data)
          -> For each candle array:
               {
                 "exchange": "binance",
                 "open_time": 1714000000000,
                 "open": 94250.50,
                 "high": 94300.00,
                 "low": 94200.00,
                 "close": 94275.00,
                 "volume": 12.5,
                 "close_time": 1714000059999,
                 "quote_volume": 1178437.50,
                 "trade_count": 847,
                 "taker_buy_base_volume": 7.2,
                 "taker_buy_quote_volume": 678780.00,
                 "confirm": null,
                 "ingested_at": "2026-04-28T05:30:00+00:00"
               }
          -> json.dumps() -> XCom push "transformed_rows"

T+5s    load() runs:
          XCom pull "transformed_rows" -> json.loads()
          DuckDB connect warehouse/datahaus.duckdb
          Execute schema.sql (CREATE TABLE IF NOT EXISTS)
          DELETE FROM curated.btc_ohlcv
            WHERE exchange='binance' AND open_time IN (1714000000000, ...)
          INSERT INTO curated.btc_ohlcv VALUES (?, ?, ..., ?)  x 100 rows
          Log: "Loaded 100 rows. Binance total: 14,832 rows."
          Close connection

T+120s  reconciliation_dag triggers (offset schedule):
          reconcile() runs:
          DuckDB connect READ-ONLY
          SELECT exchange, open_time, close
            FROM curated.btc_ohlcv
            WHERE open_time >= (now_ms - 600000)
          -> Returns rows from binance, bybit, okx for last 10 min

          detect_spread_anomalies(rows):
            For open_time=1714000000000:
              binance close=94275.00, bybit close=94280.00, okx close=94270.00
              binance-bybit spread: |94275-94280|/94277.5 = 0.005% (< 1%, OK)
              binance-okx spread:   |94275-94270|/94272.5 = 0.005% (< 1%, OK)
              bybit-okx spread:     |94280-94270|/94275.0 = 0.011% (< 1%, OK)

          No anomalies -> route_alert(outcome="PASS")
          -> Append to alert_log.jsonl
          -> (Optional Slack: "All exchanges within threshold")
```

---

## Trace: Chaos -> Detection -> Recovery

```
INJECT:
  $ python scripts/chaos_spread.py --inject
  -> Reads latest close from DuckDB: 94275.00
  -> Inserts: exchange='chaos_test', close=98988.75 (+5%)

DETECT (next reconciliation run):
  reconcile() queries last 10 min -> picks up chaos_test row
  detect_spread_anomalies():
    binance close=94275.00 vs chaos_test close=98988.75
    spread = |94275-98988.75| / 96631.875 = 4.88% > 1% threshold
    -> ANOMALY FLAGGED

  route_alert(outcome="FAIL", details="Spread anomaly: binance vs chaos_test...")
  -> Written to alert_log.jsonl
  -> Slack notification fires (if configured)

RESPOND:
  Engineer sees alert
  Opens runbook: runbooks/RB-04-spread-divergence.md
  Follows diagnosis steps

RECOVER:
  $ python scripts/chaos_spread.py --clean
  -> DELETE FROM curated.btc_ohlcv WHERE exchange='chaos_test'

  Next reconciliation run -> PASS
  -> Audit trail shows: FAIL at T, then PASS at T+5min
```

---

## Component Dependency Map

```
                    compute/adapters/base.py (ABC)
                     /          |          \
                    /           |           \
       binance.py          bybit.py        okx.py
           |                   |               |
           v                   v               v
   binance_klines_1m    bybit_klines_1m    okx_klines_1m
           |                   |               |
           +-------+-----------+-------+-------+
                   |                   |
                   v                   v
          warehouse/schema.sql    warehouse/datahaus.duckdb
                   |                   |
          +--------+--------+         |
          |                 |         |
          v                 v         v
    soda_checks/*.yml    reconciliation_dag.py
                            |
                            +---> compute/reconciliation.py
                            |       detect_spread_anomalies()
                            |       summarize_anomalies()
                            |
                            +---> observability/alert_router.py
                                    route_alert()
                                      |
                                      +--> alert_log.jsonl (always)
                                      +--> Slack webhook (if env var set)
```

---

## Key Design Decisions — Sharp Answers

| Question | Answer |
|----------|--------|
| **Why DuckDB over Postgres?** | Zero-ops. No server, no connections, no pg_hba.conf. Single file. Columnar storage is fast for OLAP. This project proves data ops discipline, not database admin. |
| **Why three exchanges?** | Three independent sources of the same metric create real reconciliation. Two is a diff. Three is a quorum problem. Same pattern as reconciling vendor feeds at a bank. |
| **Why one DAG per exchange?** | Independent failure domains. You can pause Binance for chaos testing without affecting Bybit/OKX ingestion. Independent retry, independent backfill. |
| **Why single table, not one per exchange?** | Reconciliation is a single scan. `GROUP BY open_time` gives you all exchanges in one pass. No JOINs, no query planner surprises. |
| **Why nullable columns?** | Binance gives 12 fields, OKX gives 9. Flattening to lowest common denominator loses data. Nullable columns preserve everything each exchange offers. |
| **Why Airflow standalone?** | SequentialExecutor + SQLite metadata. This project demonstrates pipeline operations, not cluster management. Moving to CeleryExecutor or KubernetesExecutor is a config change, not a rewrite. |
| **Why not Kafka?** | Kafka solves real-time streaming at scale. This is 3 API calls every 5 minutes. HTTP polling with 5-min cron is the right tool. Over-engineering would signal poor judgment. |
| **Why pure functions for reconciliation?** | No I/O means trivially unit-testable. The DAG handles I/O (query DB, route alert). The math is isolated and tested with 10 unit tests. |
| **Why does PASS also write to alert_log?** | Audit trail. You can prove the system was checking at 3am even when nothing was wrong. Absence of evidence is not evidence of absence. |
| **Why chaos scripts as first-class code?** | They're not afterthoughts. They're how you prove the system works. "We detect failures" is a claim. A chaos script that fires and triggers a Slack alert is proof. |

---

## File Quick Reference

### By Layer

```
ADAPTERS (compute/adapters/)
  base.py              ExchangeAdapter ABC — the contract
  binance.py           BinanceAdapter — 12-col format, all nullable fields populated
  bybit.py             BybitAdapter — 7-col format, reverses response, turnover->quote_volume
  okx.py               OKXAdapter — 9-col format, reverses response, has confirm field

COMPUTE (compute/)
  reconciliation.py    detect_spread_anomalies() + summarize_anomalies() — pure functions
  ingest_klines.py     Legacy transform (unused by current DAGs, tested separately)

PIPELINES (pipelines/)
  binance_klines_1m.py   ETL DAG: extract >> transform >> load (every 5 min)
  bybit_klines_1m.py     Same structure, different adapter
  okx_klines_1m.py       Same structure, different adapter
  reconciliation_dag.py  Reads DuckDB, runs spread detection, routes alert

STORAGE (warehouse/)
  schema.sql           DDL for curated.btc_ohlcv — executed idempotently on every load
  datahaus.duckdb      The database file (gitignored, created at runtime)

OBSERVABILITY (observability/)
  alert_router.py      route_alert() — JSONL always, Slack optionally
  alerts/              Output directory for alert_log.jsonl
  soda_checks/         Declarative quality rules per exchange + global

CHAOS (scripts/)
  chaos_freshness.py   Pause DAG -> stale data -> Soda freshness fails
  chaos_spread.py      Inject fake row -> reconciliation detects spread
  chaos_clear.py       Unpause DAG -> recovery
  migrate_phase2.py    One-time schema migration (Phase 1 -> Phase 2)

TESTS (tests/)
  test_adapters.py         22 tests across 3 adapter classes
  test_ingest.py           5 tests for transform_klines()
  test_reconciliation.py   10 tests for spread detection + summarization

DOCS (docs/)
  architecture.md      Five-layer architecture overview
  developer_guide.md   Setup and development instructions
  operations_manual.md Runbook index and operational procedures
  phase1_acceptance.md Phase 1 acceptance criteria
  phase2_acceptance.md Phase 2 acceptance criteria

RUNBOOKS (runbooks/)
  RB-01  Binance freshness alert
  RB-02  Bybit freshness alert
  RB-03  OKX freshness alert
  RB-04  Spread divergence alert
```

### By Function Call Chain

```
Ingestion path:
  Adapter.fetch_raw() -> Adapter.transform() -> DAG.load() -> DuckDB INSERT

Reconciliation path:
  DuckDB SELECT -> detect_spread_anomalies() -> summarize_anomalies() -> route_alert()

Alert path:
  route_alert() -> alert_log.jsonl (always) + Slack POST (optional)

Chaos path (freshness):
  chaos_freshness.py -> Airflow REST API PATCH -> DAG paused -> Soda freshness fails

Chaos path (spread):
  chaos_spread.py -> DuckDB INSERT fake row -> reconciliation detects -> route_alert(FAIL)

Recovery path:
  chaos_clear.py -> Airflow REST API PATCH -> DAG unpaused -> fresh data resumes
  chaos_spread.py --clean -> DELETE fake rows -> next reconciliation -> PASS
```

---

## The 90-Second Demo Narrative

> "Let me show you what this system looks like when it's operating."
>
> 1. **Green state** (15s): Show Airflow UI — 3 DAGs ticking green every 5 min.
>    Query DuckDB: `SELECT exchange, COUNT(*) FROM curated.btc_ohlcv GROUP BY 1`.
>    Three exchanges, thousands of rows. Show `alert_log.jsonl` — all PASS.
>
> 2. **Inject chaos** (15s): Run `python scripts/chaos_spread.py --inject`.
>    "I just inserted a fake candle with a 5% price spike."
>
> 3. **Detection fires** (15s): Trigger reconciliation DAG. Wait for completion.
>    Show `alert_log.jsonl` — new FAIL record. Show Slack notification if configured.
>    "The system detected a 4.88% spread between the real and fake exchange."
>
> 4. **Runbook response** (15s): Open `runbooks/RB-04-spread-divergence.md`.
>    "Every alert type has a runbook with severity, symptoms, diagnosis, resolution."
>
> 5. **Recovery** (15s): Run `python scripts/chaos_spread.py --clean`.
>    Trigger reconciliation again. Show PASS in `alert_log.jsonl`.
>    "Green -> chaos -> detection -> runbook -> recovery. Full loop."
>
> 6. **The point** (15s): "This isn't a tutorial pipeline. It's an operating system.
>    I built the pipeline, the quality checks, the anomaly detection, the alerting,
>    the chaos tests, and the runbooks. That's what production operations looks like."
