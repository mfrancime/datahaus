# RB-02: Bybit OHLCV Data Freshness Alert

**Severity:** P2 — Data Delayed
**Service:** datahaus / bybit_klines_1m
**Check:** `freshness(ingested_at) < 10m` on `curated.btc_ohlcv` WHERE `exchange = 'bybit'`
**Last reviewed:** 2026-04-26

---

## Symptom

Soda freshness check fails for the Bybit partition:
```
freshness(ingested_at) < 10m [FAIL]
  max_column_timestamp: 2026-04-26 03:42:00
  freshness: 0 days 00:14:22
```

The `curated.btc_ohlcv` table has not received new Bybit data within the expected 10-minute window.

---

## Likely causes (check in order)

| # | Cause | How to check |
|---|-------|-------------|
| 1 | DAG is paused | Airflow UI → DAGs → `bybit_klines_1m` toggle |
| 2 | DAG run failed | Airflow UI → DAG Runs → check last run status |
| 3 | Bybit API unreachable | `curl -s "https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=1&limit=1"` |
| 4 | Bybit rate-limited | Check Airflow task logs for HTTP 403/429 |
| 5 | Bybit geo-restricted | Bybit blocks some regions — check from different IP |
| 6 | DuckDB write lock | `ls -la warehouse/datahaus.duckdb.wal` |

---

## Diagnosis steps

### 1. Check DAG state
```bash
curl -s -u admin:admin http://localhost:8080/api/v1/dags/bybit_klines_1m | python3 -m json.tool | grep is_paused
```

### 2. Check last DAG run
```bash
curl -s -u admin:admin "http://localhost:8080/api/v1/dags/bybit_klines_1m/dagRuns?order_by=-start_date&limit=3" | python3 -m json.tool
```

### 3. Test upstream connectivity
```bash
curl -s "https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=1&limit=1" | python3 -m json.tool
```

If `retCode` is not 0, the API may be rate-limited or down.

### 4. Check DuckDB for Bybit data
```bash
cd ~/datahaus
~/.venvs/datahaus/bin/python -c "
import duckdb
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True)
print(con.execute(\"SELECT MAX(ingested_at) FROM curated.btc_ohlcv WHERE exchange = 'bybit'\").fetchone())
con.close()
"
```

---

## Resolution

### DAG paused
```bash
make chaos-clear --exchange bybit   # or: make chaos-clear
make trigger-bybit
make run-checks-all
```

### DAG run failed
```bash
make trigger-bybit
# Wait ~1-2 minutes, then verify
make run-checks-all
```

### Bybit API down / geo-restricted
1. Bybit has no public status page — check social media or forums
2. If confirmed outage, silence the alert
3. DAG retries (3x with exponential backoff) will auto-recover

---

## Communication template

```
[datahaus] Data freshness alert — Bybit BTC/USDT OHLCV

Status: Investigating / Identified / Resolved
Impact: Cross-exchange reconciliation may be incomplete
Root cause: [DAG paused / API failure / geo-restriction]
ETA to resolution: [X minutes]
```
