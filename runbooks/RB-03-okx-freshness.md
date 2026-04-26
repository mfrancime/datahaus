# RB-03: OKX OHLCV Data Freshness Alert

**Severity:** P2 — Data Delayed
**Service:** datahaus / okx_klines_1m
**Check:** `freshness(ingested_at) < 10m` on `curated.btc_ohlcv` WHERE `exchange = 'okx'`
**Last reviewed:** 2026-04-26

---

## Symptom

Soda freshness check fails for the OKX partition:
```
freshness(ingested_at) < 10m [FAIL]
  max_column_timestamp: 2026-04-26 03:42:00
  freshness: 0 days 00:14:22
```

---

## Likely causes (check in order)

| # | Cause | How to check |
|---|-------|-------------|
| 1 | DAG is paused | Airflow UI → DAGs → `okx_klines_1m` toggle |
| 2 | DAG run failed | Airflow UI → DAG Runs → check last run status |
| 3 | OKX API unreachable | `curl -s "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1m&limit=1"` |
| 4 | OKX rate-limited (40 req/2s per IP) | Check Airflow task logs for HTTP 429 |
| 5 | DuckDB write lock | `ls -la warehouse/datahaus.duckdb.wal` |

---

## Diagnosis steps

### 1. Check DAG state
```bash
curl -s -u admin:admin http://localhost:8080/api/v1/dags/okx_klines_1m | python3 -m json.tool | grep is_paused
```

### 2. Check last DAG run
```bash
curl -s -u admin:admin "http://localhost:8080/api/v1/dags/okx_klines_1m/dagRuns?order_by=-start_date&limit=3" | python3 -m json.tool
```

### 3. Test upstream connectivity
```bash
curl -s "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1m&limit=1" | python3 -m json.tool
```

If `code` is not "0", the API has an issue. OKX rate limit is 40 req/2s per IP for this endpoint (public, no auth needed).

### 4. Check DuckDB for OKX data
```bash
cd ~/datahaus
~/.venvs/datahaus/bin/python -c "
import duckdb
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True)
print(con.execute(\"SELECT MAX(ingested_at) FROM curated.btc_ohlcv WHERE exchange = 'okx'\").fetchone())
con.close()
"
```

---

## Resolution

### DAG paused
```bash
make chaos-clear --exchange okx
make trigger-okx
make run-checks-all
```

### DAG run failed
```bash
make trigger-okx
make run-checks-all
```

### OKX API rate-limited
OKX has a 40 req/2s per-IP limit on `/market/candles`. Our DAG fetches once per 5 minutes so this should not trigger unless other processes are hitting the same endpoint. If it does:
1. Check for other OKX API consumers on the same IP
2. DAG retries (3x) should auto-recover

---

## Communication template

```
[datahaus] Data freshness alert — OKX BTC/USDT OHLCV

Status: Investigating / Identified / Resolved
Impact: Cross-exchange reconciliation may be incomplete
Root cause: [DAG paused / API failure / rate limit]
ETA to resolution: [X minutes]
```
