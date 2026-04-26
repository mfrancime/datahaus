# datahaus Process Flow

Complete end-to-end documentation of how data moves through the system, how pipelines are orchestrated, and how alerts are routed.

---

## 1. High-Level Pipeline Architecture

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │                        EXTERNAL SOURCES                             │
  │                                                                     │
  │   Binance REST API        Bybit v5 REST API       OKX v5 REST API  │
  │   /api/v3/klines          /v5/market/kline         /api/v5/market/  │
  │   BTCUSDT, 1m, 100       BTCUSDT, 1, 100          candles          │
  │                                                    BTC-USDT,1m,100  │
  └──────────┬───────────────────────┬──────────────────────┬───────────┘
             │                       │                      │
             ▼                       ▼                      ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │                     EXCHANGE ADAPTERS                               │
  │                     compute/adapters/                               │
  │                                                                     │
  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
  │  │ BinanceAdapter   │  │ BybitAdapter     │  │ OKXAdapter          │ │
  │  │                  │  │                  │  │                     │ │
  │  │ fetch_raw():     │  │ fetch_raw():     │  │ fetch_raw():        │ │
  │  │  GET /klines     │  │  GET /kline      │  │  GET /candles       │ │
  │  │  12-field lists  │  │  7-field lists   │  │  9-field lists      │ │
  │  │                  │  │  reverse order   │  │  reverse order      │ │
  │  │ transform():     │  │                  │  │                     │ │
  │  │  all 14 fields   │  │ transform():     │  │ transform():        │ │
  │  │  confirm=None    │  │  7 core fields   │  │  7 core fields      │ │
  │  │                  │  │  nulls for rest  │  │  confirm=bool       │ │
  │  │                  │  │                  │  │  nulls for rest     │ │
  │  └─────────────────┘  └─────────────────┘  └─────────────────────┘ │
  └──────────┬───────────────────────┬──────────────────────┬───────────┘
             │                       │                      │
             │              Unified dict format:            │
             │  {exchange, open_time, open, high, low,      │
             │   close, volume, close_time*, quote_volume*, │
             │   trade_count*, taker_buy_base_volume*,      │
             │   taker_buy_quote_volume*, confirm*,         │
             │   ingested_at}                               │
             │              (* = nullable)                  │
             │                       │                      │
             ▼                       ▼                      ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │                     AIRFLOW ORCHESTRATION                           │
  │                     pipelines/                                      │
  │                                                                     │
  │  ┌──────────────────────────────────────────────────────────────┐   │
  │  │  binance_klines_1m    */5 * * * *                           │   │
  │  │  bybit_klines_1m      */5 * * * *                           │   │
  │  │  okx_klines_1m        */5 * * * *                           │   │
  │  │                                                              │   │
  │  │  Each DAG:  extract ──→ transform ──→ load                  │   │
  │  │             (API call)  (adapter)     (DuckDB upsert)       │   │
  │  └──────────────────────────────────────────────────────────────┘   │
  │                                                                     │
  │  ┌──────────────────────────────────────────────────────────────┐   │
  │  │  reconciliation       2-57/5 * * * *  (offset 2 min)       │   │
  │  │                                                              │   │
  │  │  reconcile: query last 10min → detect_spread_anomalies      │   │
  │  │             → route_alert                                    │   │
  │  └──────────────────────────────────────────────────────────────┘   │
  └──────────────────────────────┬──────────────────────────────────────┘
                                 │
                                 ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │                     DUCKDB WAREHOUSE                                │
  │                     warehouse/datahaus.duckdb                       │
  │                                                                     │
  │  curated.btc_ohlcv                                                 │
  │  ┌─────────────────────────────────────────────────────────────┐   │
  │  │  PK: (exchange, open_time)                                  │   │
  │  │                                                              │   │
  │  │  exchange │ open_time     │ OHLCV      │ exchange-specific  │   │
  │  │  ─────────┼───────────────┼────────────┼────────────────────│   │
  │  │  binance  │ 1777214100000 │ full data  │ close_time, etc.   │   │
  │  │  bybit    │ 1777214100000 │ full data  │ quote_volume only  │   │
  │  │  okx      │ 1777214100000 │ full data  │ confirm flag       │   │
  │  └─────────────────────────────────────────────────────────────┘   │
  └──────────────────────────────┬──────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
  ┌─────────────────────────┐  ┌──────────────────────────────────────┐
  │  SODA CORE CHECKS       │  │  RECONCILIATION                     │
  │  17 checks total        │  │  compute/reconciliation.py           │
  │                         │  │                                      │
  │  Global:                │  │  detect_spread_anomalies()           │
  │  · row_count > 0        │  │  · Groups by open_time               │
  │  · dup(exchange,time)=0 │  │  · Compares close prices pairwise    │
  │                         │  │  · Flags >1% spread                  │
  │  Per-exchange:          │  │                                      │
  │  · freshness < 10m      │  │  summarize_anomalies()               │
  │  · row_count > 0        │  │  · Human-readable alert text         │
  │  · dup(open_time) = 0   │  │                                      │
  │  · field NOT NULL checks│  └──────────────────┬───────────────────┘
  └─────────────────────────┘                     │
                                                  ▼
                                   ┌──────────────────────────────────┐
                                   │  ALERT ROUTER                    │
                                   │  observability/alert_router.py   │
                                   │                                  │
                                   │  route_alert()                   │
                                   │  ├── ALWAYS: append to           │
                                   │  │   alert_log.jsonl             │
                                   │  └── IF SLACK_WEBHOOK_URL set:   │
                                   │      POST to Slack channel       │
                                   └──────────────────────────────────┘
```

---

## 2. Single DAG Execution Lifecycle

Each exchange DAG (binance/bybit/okx) follows the identical 3-task ETL pattern:

### Task 1: Extract

```
Input:  None
Output: XCom key "raw_klines" (JSON string)

Steps:
1. Import the exchange adapter (e.g. BinanceAdapter)
2. Call adapter.fetch_raw(symbol, interval, limit)
   - Makes HTTP GET to exchange public API
   - Validates response (HTTP status + API error codes)
   - Bybit/OKX: reverses response (newest-first → chronological)
3. Serialize raw response to JSON
4. Push to XCom for next task

Failure modes:
- HTTP timeout (30s) → Airflow retries (3x, exponential backoff)
- API rate limit (429) → Airflow retries
- API error code → RuntimeError raised → Airflow retries
- Network unreachable → ConnectionError → Airflow retries
```

### Task 2: Transform

```
Input:  XCom key "raw_klines" from extract
Output: XCom key "transformed_rows" (JSON string of row dicts)

Steps:
1. Pull raw JSON from XCom
2. Deserialize to list of lists
3. Call adapter.transform(raw_data)
   - Maps exchange-specific field positions to unified schema
   - Casts string values to float/int
   - Sets exchange-specific nullable fields (None if not available)
   - Stamps ingested_at = UTC now
4. Serialize row dicts to JSON
5. Push to XCom for next task

Failure modes:
- Malformed API response → IndexError/ValueError → task fails
- No data returned → empty list passed through
```

### Task 3: Load

```
Input:  XCom key "transformed_rows" from transform
Output: Rows in DuckDB curated.btc_ohlcv

Steps:
1. Pull transformed rows from XCom
2. Deserialize to list of dicts
3. If empty → log warning, return (no-op)
4. Connect to DuckDB (warehouse/datahaus.duckdb)
5. Ensure schema exists (run schema.sql DDL — idempotent)
6. DELETE existing rows: WHERE exchange = '{name}' AND open_time IN (...)
7. INSERT new rows (14 columns each)
8. Log row count
9. Close connection

Failure modes:
- DuckDB locked (WAL file) → connection error → Airflow retries
- Schema mismatch → SQL error → task fails
- Disk full → write error → task fails

Upsert strategy:
- DELETE + INSERT (not MERGE) — simpler, DuckDB-compatible
- Scoped to exchange: never touches other exchanges' data
- Idempotent: re-running with same data produces same result
```

---

## 3. Reconciliation Pipeline

```
Schedule: 2-57/5 * * * * (runs at :02, :07, :12, ... — offset 2min from ingestion)

┌──────────────────────────────────────────────────────────────────┐
│  Step 1: Query recent data                                       │
│                                                                   │
│  SELECT exchange, open_time, close                               │
│  FROM curated.btc_ohlcv                                          │
│  WHERE open_time >= (now_epoch_ms - 600000)  -- last 10 minutes  │
│  ORDER BY open_time                                              │
│                                                                   │
│  Result: ~30 rows per exchange × 3 exchanges = ~90 rows          │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 2: Detect spread anomalies                                 │
│                                                                   │
│  For each unique open_time:                                      │
│    For each pair of exchanges (i, j):                            │
│      midpoint = (close_i + close_j) / 2                          │
│      spread = |close_i - close_j| / midpoint                    │
│      if spread > 0.01 (1%):                                     │
│        → ANOMALY                                                 │
│                                                                   │
│  Example:                                                        │
│  open_time=1777214100000:                                        │
│    binance close = 78072.31                                      │
│    bybit close   = 78090.50  → spread = 0.023% ✓ OK             │
│    okx close     = 78030.30  → spread = 0.054% ✓ OK             │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 3: Route alert                                             │
│                                                                   │
│  If anomalies found:                                             │
│    outcome = "FAIL"                                              │
│    details = "SPREAD ALERT: N anomalies detected\n..."           │
│  Else:                                                           │
│    outcome = "PASS"                                              │
│    details = "No spread anomalies detected."                     │
│                                                                   │
│  route_alert(                                                    │
│    check_name="spread_anomaly",                                  │
│    table="curated.btc_ohlcv",                                   │
│    exchange="cross-exchange",                                    │
│    outcome=outcome,                                              │
│    details=details                                               │
│  )                                                               │
│                                                                   │
│  → Append JSONL to observability/alerts/alert_log.jsonl          │
│  → If SLACK_WEBHOOK_URL set: POST formatted message              │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. Alert Routing Flow

```
                    ┌─────────────────┐
                    │  Alert Source    │
                    │                 │
                    │  · Reconciliation│
                    │    DAG          │
                    │  · (Future:     │
                    │    Soda hooks)  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  route_alert()  │
                    │                 │
                    │  check_name     │
                    │  table          │
                    │  exchange       │
                    │  outcome        │
                    │  details        │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
                    ▼                 ▼
           ┌──────────────┐  ┌───────────────┐
           │  FILE SINK   │  │  SLACK SINK   │
           │  (always)    │  │  (optional)   │
           │              │  │               │
           │  Append to:  │  │  POST to:     │
           │  alert_log   │  │  webhook URL  │
           │  .jsonl      │  │               │
           │              │  │  Formatted:   │
           │  Format:     │  │  :emoji: title│
           │  {timestamp, │  │  exchange     │
           │   check,     │  │  table        │
           │   table,     │  │  outcome      │
           │   exchange,  │  │  ```details```│
           │   outcome,   │  │               │
           │   details}   │  │  Env var:     │
           │              │  │  SLACK_WEBHOOK │
           │              │  │  _URL         │
           └──────────────┘  └───────────────┘
```

### Alert JSONL Record Schema

```json
{
  "timestamp": "2026-04-26T14:35:56.923975+00:00",
  "check_name": "spread_anomaly",
  "table": "curated.btc_ohlcv",
  "exchange": "cross-exchange",
  "outcome": "PASS|FAIL|WARN",
  "details": "Human-readable details string"
}
```

---

## 5. Scheduling Timeline

All times are wall-clock minutes within each hour:

```
Minute:  00  01  02  03  04  05  06  07  08  09  10  ...
         ─────────────────────────────────────────────
Binance: ▓▓▓  .   .   .   .  ▓▓▓  .   .   .   .  ▓▓▓
Bybit:    ▓▓▓  .   .   .   .  ▓▓▓  .   .   .   .  ▓▓▓
OKX:       ▓▓▓  .   .   .   .  ▓▓▓  .   .   .   .  ▓▓▓
Recon:      .  ▓▓   .   .   .   .  ▓▓   .   .   .   .

Legend: ▓ = task running,  . = idle

Schedule cron expressions:
  Exchange DAGs:     */5 * * * *      (every 5 min)
  Reconciliation:    2-57/5 * * * *   (every 5 min, offset +2)
```

The 2-minute offset ensures ingestion DAGs have time to complete before reconciliation queries the data. With SequentialExecutor, DAGs run one at a time — worst case all 3 exchange DAGs take ~3 minutes total, and reconciliation starts at minute 2 of the next cycle.

---

## 6. Data Schema Flow

### Raw API → Unified Schema Mapping

| Unified Field | Binance (v3) | Bybit (v5) | OKX (v5) |
|---------------|-------------|------------|----------|
| `exchange` | `"binance"` | `"bybit"` | `"okx"` |
| `open_time` | `[0]` (int ms) | `[0]` (str ms) → int | `[0]` (str ms) → int |
| `open` | `[1]` (str) → float | `[1]` (str) → float | `[1]` (str) → float |
| `high` | `[2]` (str) → float | `[2]` (str) → float | `[2]` (str) → float |
| `low` | `[3]` (str) → float | `[3]` (str) → float | `[3]` (str) → float |
| `close` | `[4]` (str) → float | `[4]` (str) → float | `[4]` (str) → float |
| `volume` | `[5]` (str) → float | `[5]` (str) → float | `[5]` (str) → float |
| `close_time` | `[6]` (int ms) | `None` | `None` |
| `quote_volume` | `[7]` (str) → float | `[6]` turnover → float | `[7]` volCcyQuote → float |
| `trade_count` | `[8]` (int) | `None` | `None` |
| `taker_buy_base_volume` | `[9]` (str) → float | `None` | `None` |
| `taker_buy_quote_volume` | `[10]` (str) → float | `None` | `None` |
| `confirm` | `None` | `None` | `[8]` "0"/"1" → bool |
| `ingested_at` | UTC ISO timestamp | UTC ISO timestamp | UTC ISO timestamp |

### API Response Ordering

| Exchange | Response Order | Adapter Action |
|----------|---------------|----------------|
| Binance | Chronological (oldest first) | No reorder needed |
| Bybit | Reverse chronological (newest first) | `data.reverse()` |
| OKX | Reverse chronological (newest first) | `data.reverse()` |

---

## 7. Upsert Strategy

```
For each DAG load task:

1. Collect open_times from transformed rows
2. DELETE WHERE exchange = '{exchange}' AND open_time IN ({open_times})
3. INSERT all transformed rows

This is a "delete-then-insert" upsert pattern:
- Scoped to single exchange (never touches other exchanges' data)
- Handles both new rows and updated rows (re-ingestion)
- Safe with SequentialExecutor (no concurrent writes)
- Idempotent: same input → same output
```

---

## 8. Error Handling & Retry Strategy

| Component | Retry Config | Backoff |
|-----------|-------------|---------|
| Exchange DAGs | 3 retries | Exponential (1m base) |
| Reconciliation DAG | 1 retry | Linear (1m) |
| HTTP requests | 30s timeout | Per-request |
| Execution timeout | 5 minutes | Hard kill |
| Alert router (Slack) | 0 retries | Fail-open (logged, non-fatal) |

### Failure Cascade

```
API timeout → Airflow retry (up to 3x)
  └→ All retries fail → Task marked FAILED
      └→ DAG run marked FAILED
          └→ Next scheduled run starts fresh
              └→ Freshness check fails after 10 minutes
                  └→ Operator investigates per runbook
```
