# RB-01: Binance OHLCV Data Freshness Alert

**Severity:** P2 — Data Delayed
**Service:** datahaus / binance_klines_1m
**Check:** `freshness(ingested_at) < 10m` on `curated.btc_ohlcv`
**Last reviewed:** 2026-04-27

---

## Symptom

Soda freshness check fails with message like:
```
freshness(ingested_at) < 10m [FAIL]
  max_column_timestamp: 2025-01-15 03:42:00
  freshness: 0 days 00:14:22
```

The `curated.btc_ohlcv` table has not received new data within the expected 10-minute window.

---

## Likely causes (check in order)

| # | Cause | How to check |
|---|-------|-------------|
| 1 | DAG is paused | Airflow UI → DAGs → `binance_klines_1m` toggle |
| 2 | DAG run failed | Airflow UI → DAG Runs → check last run status |
| 3 | Binance API unreachable | `curl -s https://api.binance.com/api/v3/ping` |
| 4 | Binance rate-limited | Check Airflow task logs for HTTP 429 |
| 5 | DuckDB write lock | `ls -la warehouse/datahaus.duckdb.wal` |
| 6 | Airflow scheduler down | `ps aux | grep airflow` — scheduler process missing |

---

## Diagnosis steps

### 1. Check DAG state
```bash
curl -s -u admin:admin http://localhost:8080/api/v1/dags/binance_klines_1m | python3 -m json.tool | grep is_paused
```

If `"is_paused": true` → this was either intentional (maintenance) or chaos injection. Skip to Resolution.

### 2. Check last DAG run
```bash
curl -s -u admin:admin "http://localhost:8080/api/v1/dags/binance_klines_1m/dagRuns?order_by=-start_date&limit=3" | python3 -m json.tool
```

Look at `state`. If `failed`, check task logs:
```bash
curl -s -u admin:admin "http://localhost:8080/api/v1/dags/binance_klines_1m/dagRuns/{RUN_ID}/taskInstances" | python3 -m json.tool
```

### 3. Test upstream connectivity
```bash
curl -s "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1" | python3 -m json.tool
```

If this returns data, the API is fine. If it returns 451 or connection refused, Binance may be geo-blocked or down.

### 4. Check DuckDB health
```bash
cd ~/datahaus
~/.venvs/datahaus/bin/python -c "
import duckdb
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True)
print(con.execute('SELECT MAX(ingested_at) FROM curated.btc_ohlcv').fetchone())
con.close()
"
```

---

## Resolution

### DAG paused (most common)
```bash
# Un-pause
make chaos-clear

# Trigger immediate run
make trigger-pipeline

# Verify recovery after run completes (~1-2 minutes)
make run-checks
```

### DAG run failed — transient API error
The DAG has 3 retries with exponential backoff built in. If all retries failed:
```bash
# Clear the failed state and trigger
make trigger-pipeline
```

### Binance API down
1. Check https://www.binance.com/en/support for status
2. If confirmed outage, silence the alert (note in action log)
3. Monitor for recovery
4. No action needed — DAG retries will pick up automatically

### DuckDB locked
```bash
# Check for stale WAL file
ls -la warehouse/datahaus.duckdb.wal

# If WAL exists and no process is writing, remove it
rm warehouse/datahaus.duckdb.wal

# Re-trigger
make trigger-pipeline
```

---

## Communication template

**For stakeholders (Slack/email):**
```
[datahaus] Data freshness alert — BTC/USDT OHLCV

Status: Investigating / Identified / Resolved
Impact: Downstream consumers may see stale 1-minute candle data
Root cause: [DAG paused / API failure / scheduler issue]
ETA to resolution: [X minutes]
Next update: [time]
```

---

## Postmortem template

**Title:** BTC/USDT data freshness breach — [DATE]

**Timeline:**
- HH:MM — Alert fired (freshness check failed)
- HH:MM — Acknowledged by [name]
- HH:MM — Root cause identified: [description]
- HH:MM — Resolution applied
- HH:MM — Freshness check passing again

**Root cause:** [Describe what actually happened]

**Impact:** Data was stale for [duration]. [N] downstream consumers were affected.

**Action items:**
- [ ] [Preventive action 1]
- [ ] [Monitoring improvement]
- [ ] [Documentation update]
