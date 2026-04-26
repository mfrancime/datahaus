# RB-04: Cross-Exchange Spread Divergence Alert

**Severity:** P3 — Anomaly Detected
**Service:** datahaus / reconciliation
**Check:** `spread_anomaly` — close price divergence > 1% between any two exchanges
**Last reviewed:** 2026-04-26

---

## Symptom

The reconciliation DAG detects close-price spreads exceeding 1% between exchanges. Alert appears in `observability/alerts/alert_log.jsonl`:
```json
{"check_name": "spread_anomaly", "outcome": "FAIL", "exchange": "cross-exchange", ...}
```

Or via `make view-alerts`:
```
SPREAD ALERT: 2 anomalies detected
  [1704067200000] binance=42050.75 vs okx=43000.00 (spread: 2.24%, threshold: 1.00%)
```

---

## Likely causes (check in order)

| # | Cause | How to check |
|---|-------|-------------|
| 1 | Chaos injection (chaos_spread.py) | Check for `exchange = 'chaos_test'` rows |
| 2 | Stale data from one exchange | Compare `MAX(ingested_at)` per exchange |
| 3 | Exchange API returning bad data | Spot-check raw prices against exchange website |
| 4 | Flash crash on one exchange | Check exchange order books / social media |
| 5 | Legitimate market divergence | Rare but possible during high-volatility events |

---

## Diagnosis steps

### 1. Check for chaos injection
```bash
cd ~/datahaus
~/.venvs/datahaus/bin/python -c "
import duckdb
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True)
print(con.execute(\"SELECT * FROM curated.btc_ohlcv WHERE exchange = 'chaos_test'\").fetchdf().to_string())
con.close()
"
```

If rows exist → this is a chaos test. Run `make chaos-spread-clean` to clear.

### 2. Check data freshness per exchange
```bash
~/.venvs/datahaus/bin/python -c "
import duckdb
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True)
print(con.execute('SELECT exchange, COUNT(*) as rows, MAX(ingested_at) as latest FROM curated.btc_ohlcv GROUP BY exchange').fetchdf().to_string())
con.close()
"
```

If one exchange is significantly older → the spread may be from stale data, not real divergence. See RB-01/02/03 for freshness issues.

### 3. Spot-check prices
```bash
# Compare latest close prices across exchanges
~/.venvs/datahaus/bin/python -c "
import duckdb
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True)
print(con.execute('''
    SELECT exchange, open_time, close
    FROM curated.btc_ohlcv
    WHERE open_time = (SELECT MAX(open_time) FROM curated.btc_ohlcv)
    ORDER BY exchange
''').fetchdf().to_string())
con.close()
"
```

Cross-reference against live exchange prices to confirm if the data is accurate.

---

## Resolution

### Chaos injection
```bash
make chaos-spread-clean
make run-reconciliation   # should now PASS
```

### Stale data causing false spread
Fix the underlying freshness issue per RB-01/02/03. Re-trigger ingestion:
```bash
make trigger-all
# Wait for completion, then:
make run-reconciliation
```

### Legitimate spread divergence
1. Document the event (timestamp, exchanges, spread amount)
2. If spread persists across multiple candles, this is noteworthy market data
3. No action needed unless this triggers downstream trading logic

---

## Tuning the threshold

The default threshold is 1%. To change it, edit `compute/reconciliation.py`:
```python
detect_spread_anomalies(rows, threshold=0.02)  # 2% threshold
```

Consider:
- **< 0.5%**: Too noisy — normal market microstructure creates small spreads
- **1% (default)**: Good balance for BTC/USDT on major exchanges
- **> 2%**: Only catches extreme events
