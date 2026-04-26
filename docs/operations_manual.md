# datahaus Operations Manual (MOP)

Method of Procedure for operating, monitoring, and troubleshooting the datahaus platform.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Daily Operations](#2-daily-operations)
3. [Startup & Shutdown](#3-startup--shutdown)
4. [Monitoring Procedures](#4-monitoring-procedures)
5. [Incident Response](#5-incident-response)
6. [Chaos Testing Procedures](#6-chaos-testing-procedures)
7. [Maintenance Procedures](#7-maintenance-procedures)
8. [Configuration Reference](#8-configuration-reference)
9. [Troubleshooting Guide](#9-troubleshooting-guide)
10. [Escalation Matrix](#10-escalation-matrix)

---

## 1. System Overview

### Components

| Component | Technology | Location | Port |
|-----------|-----------|----------|------|
| Scheduler + Webserver | Apache Airflow 2.10.5 (standalone) | `.airflow/` | 8080 |
| Warehouse | DuckDB (embedded) | `warehouse/datahaus.duckdb` | N/A |
| Data quality | Soda Core 3.5.6 | `observability/soda_checks/` | N/A |
| Alert log | JSONL file | `observability/alerts/alert_log.jsonl` | N/A |
| Alert sink (optional) | Slack webhook | `SLACK_WEBHOOK_URL` env var | N/A |

### Pipelines

| DAG ID | Schedule | Source | Description |
|--------|----------|--------|-------------|
| `binance_klines_1m` | `*/5 * * * *` | Binance REST v3 | BTC/USDT 1m klines |
| `bybit_klines_1m` | `*/5 * * * *` | Bybit REST v5 | BTC/USDT 1m klines |
| `okx_klines_1m` | `*/5 * * * *` | OKX REST v5 | BTC/USDT 1m candles |
| `reconciliation` | `2-57/5 * * * *` | DuckDB (internal) | Cross-exchange spread detection |

### SLAs

| Metric | Target | Check |
|--------|--------|-------|
| Data freshness (per exchange) | < 10 minutes | Soda `freshness(ingested_at)` |
| Cross-exchange spread | < 1% | Reconciliation DAG |
| Pipeline success rate | 100% (with retries) | Airflow DAG state |
| Data uniqueness | 0 duplicates | Soda `duplicate_count` |

---

## 2. Daily Operations

### Morning Checklist

```bash
# 1. Verify Airflow is running
curl -s http://localhost:8080/health | python3 -m json.tool

# 2. Check all DAGs are active (not paused)
curl -s -u admin:admin http://localhost:8080/api/v1/dags | \
  python3 -c "import json,sys; [print(f'{d[\"dag_id\"]:30s} paused={d[\"is_paused\"]}') for d in json.load(sys.stdin)['dags']]"

# 3. Check data freshness
make db-query-all

# 4. Run data quality checks
make run-checks-all

# 5. Review recent alerts
make view-alerts
```

### Expected Output (Healthy State)

```
# db-query-all
  exchange  rows                     latest
0  binance   204 2026-04-26 14:35:44.393052
1    bybit   101 2026-04-26 14:35:50.866956
2      okx   100 2026-04-26 14:36:29.763705

# run-checks-all
17/17 checks PASSED
All is good. No failures. No warnings. No errors.

# view-alerts
{"outcome": "PASS", "check_name": "spread_anomaly", ...}
```

### Shift Handover Template

```
datahaus Shift Handover — [DATE] [TIME]

System Status: GREEN / YELLOW / RED

Pipelines:
  binance_klines_1m: [running/paused/failed]
  bybit_klines_1m:   [running/paused/failed]
  okx_klines_1m:     [running/paused/failed]
  reconciliation:    [running/paused/failed]

Data freshness:
  Binance: [latest timestamp]
  Bybit:   [latest timestamp]
  OKX:     [latest timestamp]

Soda checks: [N]/17 passed
Alerts: [summary of any FAIL alerts in last 24h]

Open incidents: [list or "None"]
Notes for next shift: [anything unusual]
```

---

## 3. Startup & Shutdown

### Full System Startup

```bash
cd ~/datahaus

# Step 1: Initialize (first time only)
make setup              # install dependencies
make airflow-init       # init Airflow DB + admin user
make db-init            # create DuckDB schema

# Step 2: Start Airflow
make airflow            # starts scheduler + webserver on :8080
                        # Ctrl+C to stop

# Step 3: Verify DAGs are loaded (in another terminal)
curl -s -u admin:admin http://localhost:8080/api/v1/dags | python3 -m json.tool
# Should show 4 DAGs

# Step 4: Un-pause DAGs if needed
make trigger-all        # un-pauses and triggers all exchange DAGs

# Step 5: Verify data flowing
sleep 120               # wait for DAGs to complete
make db-query-all       # should show rows for all 3 exchanges
make run-checks-all     # 17/17 should pass
```

### Graceful Shutdown

```bash
# Ctrl+C in the Airflow terminal
# OR:
kill $(cat .airflow/airflow-webserver.pid) 2>/dev/null
pkill -f "airflow scheduler"
```

### Emergency Stop (kill all Airflow processes)

```bash
pkill -f airflow
```

### Startup After Shutdown

```bash
make airflow            # Airflow resumes from where it left off
                        # Scheduled DAGs will catch up automatically
```

---

## 4. Monitoring Procedures

### 4.1 Airflow UI Monitoring

**URL:** http://localhost:8080 (admin/admin)

| What to Check | Where | Healthy State |
|---------------|-------|---------------|
| DAG toggle state | DAGs list → toggle | All 4 ON (not paused) |
| Last run state | DAGs list → recent runs | Green circles (success) |
| Task duration | DAG → Graph → click task | < 60s per task |
| Scheduler heartbeat | Admin → Health | "Healthy" |

### 4.2 Command-Line Monitoring

```bash
# Data freshness — run every shift or after incidents
make db-query-all

# Full data quality — run every shift
make run-checks-all

# Alert history — check for FAIL outcomes
make view-alerts

# Specific exchange status
curl -s -u admin:admin \
  "http://localhost:8080/api/v1/dags/binance_klines_1m/dagRuns?order_by=-start_date&limit=5" \
  | python3 -m json.tool

# DuckDB row counts by exchange
~/.venvs/datahaus/bin/python -c "
import duckdb
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True)
print(con.execute('''
  SELECT exchange,
         COUNT(*) as rows,
         MIN(open_time) as earliest,
         MAX(open_time) as latest,
         MAX(ingested_at) as last_ingested
  FROM curated.btc_ohlcv
  GROUP BY exchange ORDER BY exchange
''').fetchdf().to_string())
con.close()
"
```

### 4.3 Soda Check Catalog

| Check File | Exchange | Checks | What It Validates |
|-----------|----------|--------|-------------------|
| `btc_ohlcv.yml` | Global | 2 | Row count > 0, no cross-exchange PK duplicates |
| `binance_ohlcv.yml` | Binance | 8 | Freshness, row count, duplicates, 5 NOT NULL fields |
| `bybit_ohlcv.yml` | Bybit | 3 | Freshness, row count, duplicates |
| `okx_ohlcv.yml` | OKX | 4 | Freshness, row count, duplicates, confirm NOT NULL |

**Total: 17 checks**

Run individual exchange checks:
```bash
# Just Binance
cd ~/datahaus && ~/.venvs/datahaus/bin/soda scan \
  -d datahaus -c observability/soda_checks/configuration.yml \
  observability/soda_checks/binance_ohlcv.yml

# Just Bybit
cd ~/datahaus && ~/.venvs/datahaus/bin/soda scan \
  -d datahaus -c observability/soda_checks/configuration.yml \
  observability/soda_checks/bybit_ohlcv.yml
```

---

## 5. Incident Response

### Incident Classification

| Severity | Trigger | Response Time | Runbook |
|----------|---------|--------------|---------|
| P2 | Single exchange freshness breach | 15 minutes | RB-01/02/03 |
| P2 | All exchanges freshness breach | 5 minutes | RB-01 + check scheduler |
| P3 | Cross-exchange spread > 1% | 30 minutes | RB-04 |
| P4 | Soda check failure (non-freshness) | Next shift | Investigate + fix |

### Incident Response Workflow

```
1. DETECT
   └→ Soda check fails OR alert_log shows FAIL
       └→ Identify which check/exchange

2. ACKNOWLEDGE
   └→ Note the time in your shift log
   └→ Open the relevant runbook (RB-01 through RB-04)

3. DIAGNOSE
   └→ Follow runbook diagnosis steps in order
   └→ Most common: DAG paused (step 1 in all runbooks)

4. RESOLVE
   └→ Apply the fix per runbook
   └→ Verify with: make run-checks-all

5. COMMUNICATE
   └→ Use the communication template in the runbook
   └→ If Slack is configured: alert is auto-routed

6. DOCUMENT
   └→ Fill in the postmortem template (if P2+)
   └→ Add action items
```

### Quick Resolution Commands

```bash
# Most common fix: un-pause and re-trigger
make chaos-clear ARGS="--exchange all"   # un-pause all DAGs
make trigger-all                          # trigger immediately
sleep 120                                 # wait for completion
make run-checks-all                       # verify recovery

# Check specific DAG status
curl -s -u admin:admin http://localhost:8080/api/v1/dags/bybit_klines_1m | python3 -m json.tool

# Check for DuckDB lock
ls -la warehouse/datahaus.duckdb.wal

# Test upstream API connectivity
curl -s "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1" | head -c 100
curl -s "https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=1&limit=1" | head -c 100
curl -s "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1m&limit=1" | head -c 100
```

### Runbook Index

| ID | Title | When to Use |
|----|-------|------------|
| [RB-01](../runbooks/RB-01-binance-freshness.md) | Binance OHLCV Freshness | Binance Soda freshness check fails |
| [RB-02](../runbooks/RB-02-bybit-freshness.md) | Bybit OHLCV Freshness | Bybit Soda freshness check fails |
| [RB-03](../runbooks/RB-03-okx-freshness.md) | OKX OHLCV Freshness | OKX Soda freshness check fails |
| [RB-04](../runbooks/RB-04-spread-divergence.md) | Spread Divergence | Reconciliation detects >1% spread |

---

## 6. Chaos Testing Procedures

Chaos tests simulate real failure modes to validate monitoring and runbooks.

### 6.1 Freshness Chaos (Pipeline Stall)

**Purpose:** Verify that Soda freshness checks catch stalled pipelines.

```bash
# Step 1: Inject — pause one or more DAGs
make chaos-freshness                        # pause Binance only
make chaos-freshness-bybit                  # pause Bybit only
make chaos-freshness-okx                    # pause OKX only
make chaos-freshness-all                    # pause all three

# Step 2: Wait — let freshness threshold expire (>10 minutes)
sleep 600

# Step 3: Verify — freshness check should FAIL
make run-checks-all
# Expected: freshness(ingested_at) < 10m [FAIL] for paused exchange(s)

# Step 4: Recover — un-pause and re-trigger
make chaos-clear ARGS="--exchange all"
make trigger-all
sleep 120
make run-checks-all
# Expected: 17/17 PASSED
```

### 6.2 Spread Chaos (Price Anomaly)

**Purpose:** Verify that reconciliation detects cross-exchange divergence.

```bash
# Step 1: Inject — insert fake price row (+5% close)
make chaos-spread
# Output shows: real close vs fake close

# Step 2: Trigger reconciliation
make run-reconciliation
# Wait for DAG to complete

# Step 3: Verify — alert should fire
make view-alerts
# Expected: {"outcome": "FAIL", "check_name": "spread_anomaly", ...}

# Step 4: Clean up
make chaos-spread-clean

# Step 5: Verify recovery
make run-reconciliation
make view-alerts
# Expected: latest alert is PASS
```

### 6.3 Chaos Test Matrix

| Test | Injection | Detection | Recovery |
|------|-----------|-----------|----------|
| Single exchange stall | `chaos-freshness --exchange bybit` | Soda freshness FAIL | `chaos-clear`, `trigger-bybit` |
| All exchanges stall | `chaos-freshness-all` | Multiple Soda FAIL | `chaos-clear --exchange all`, `trigger-all` |
| Spread anomaly | `chaos-spread` | Reconciliation FAIL alert | `chaos-spread-clean` |

---

## 7. Maintenance Procedures

### 7.1 Schema Migration (Phase 1 → Phase 2)

**When:** Upgrading from Phase 1 to Phase 2 for the first time.

```bash
# Idempotent — safe to run multiple times
make db-migrate

# Expected output (first run):
#   Adding exchange column and migrating...
#   Migration step 1: columns added, existing rows tagged as binance.
#   Recreating table with new PK (exchange, open_time)...
#   Migration complete. 103 rows preserved with PK (exchange, open_time).

# Expected output (subsequent runs):
#   Schema already has exchange column — no migration needed. (103 rows)
```

### 7.2 DuckDB Maintenance

```bash
# Check database size
ls -lh warehouse/datahaus.duckdb

# Check row counts per exchange
make db-query-all

# Direct SQL query
~/.venvs/datahaus/bin/python -c "
import duckdb
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True)
print(con.execute('YOUR SQL HERE').fetchdf().to_string())
con.close()
"

# Compact the database (run during maintenance window)
~/.venvs/datahaus/bin/python -c "
import duckdb
con = duckdb.connect('warehouse/datahaus.duckdb')
con.execute('CHECKPOINT')
con.close()
print('Checkpoint complete.')
"
```

### 7.3 Alert Log Rotation

The alert log grows unbounded. Rotate periodically:

```bash
# Archive and rotate
mv observability/alerts/alert_log.jsonl \
   observability/alerts/alert_log.$(date +%Y%m%d).jsonl
# New alerts will create a fresh file automatically
```

### 7.4 Dependency Updates

```bash
# Check for outdated packages
~/.venvs/datahaus/bin/pip list --outdated

# Update (test locally first)
make setup   # re-runs pip install with pinned versions
make test    # verify nothing broke
```

---

## 8. Configuration Reference

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AIRFLOW_HOME` | Set by Makefile | `.airflow/` | Airflow metadata directory |
| `AIRFLOW__CORE__DAGS_FOLDER` | Set by Makefile | `pipelines/` | DAG file location |
| `JAVA_HOME` | Yes | `/usr/lib/jvm/java-17-openjdk-amd64` | For PySpark (if used) |
| `SLACK_WEBHOOK_URL` | No | None | Slack incoming webhook for alerts |

### Airflow Configuration

| Setting | Value | Notes |
|---------|-------|-------|
| Executor | SequentialExecutor | Single-threaded, prevents concurrent DuckDB writes |
| Metadata DB | SQLite | Adequate for standalone mode |
| Auth | admin/admin | Local-only, change in production |
| Web port | 8080 | http://localhost:8080 |

### Pipeline Parameters

| Parameter | Value | Set In |
|-----------|-------|--------|
| Binance symbol | `BTCUSDT` | `BinanceAdapter.fetch_raw()` |
| Bybit symbol | `BTCUSDT` | `BybitAdapter.fetch_raw()` |
| OKX symbol | `BTC-USDT` | `OKXAdapter.fetch_raw()` |
| Interval | 1 minute | Each adapter |
| Candle limit | 100 per fetch | Each adapter |
| Schedule | Every 5 minutes | Each DAG |
| Freshness SLA | 10 minutes | Soda checks |
| Spread threshold | 1% | `reconciliation.py` |
| HTTP timeout | 30 seconds | Each adapter |
| Max retries | 3 (exchange), 1 (reconciliation) | DAG default_args |

### API Endpoints

| Exchange | Endpoint | Auth | Rate Limit |
|----------|----------|------|-----------|
| Binance | `https://api.binance.com/api/v3/klines` | None (public) | 1200 req/min per IP |
| Bybit | `https://api.bybit.com/v5/market/kline` | None (public) | 600 req/5s per IP (global) |
| OKX | `https://www.okx.com/api/v5/market/candles` | None (public) | 40 req/2s per IP |

---

## 9. Troubleshooting Guide

### Problem: "No module named 'compute'" in Airflow task

**Cause:** `sys.path` not set in task function.
**Fix:** Each task function adds `sys.path.insert(0, str(PROJECT_ROOT))` before importing.

### Problem: DuckDB "Could not set lock" error

**Cause:** Another process has the database open for writing.
**Fix:**
```bash
# Check for WAL file
ls -la warehouse/datahaus.duckdb.wal

# Check for processes
lsof warehouse/datahaus.duckdb 2>/dev/null

# If no active process, remove WAL
rm -f warehouse/datahaus.duckdb.wal
```

### Problem: Bybit returns `retCode != 0`

**Cause:** Invalid parameters or Bybit API issue.
**Fix:** Test manually:
```bash
curl -s "https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=1&limit=1" | python3 -m json.tool
```

### Problem: OKX returns `code != "0"`

**Cause:** Rate limit or invalid instrument ID.
**Fix:** OKX uses `BTC-USDT` (not `BTCUSDT`). Test:
```bash
curl -s "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1m&limit=1" | python3 -m json.tool
```

### Problem: Reconciliation shows no rows

**Cause:** The query window (last 10 minutes of `open_time`) may not match ingested data if the system was recently started.
**Fix:** Trigger all DAGs and wait for fresh data:
```bash
make trigger-all
sleep 120
make run-reconciliation
```

### Problem: Soda freshness check fails after system restart

**Cause:** Data was ingested before shutdown but `ingested_at` is now older than 10 minutes.
**Fix:** Trigger fresh ingestion:
```bash
make trigger-all
sleep 120
make run-checks-all
```

---

## 10. Escalation Matrix

| Level | When | Action |
|-------|------|--------|
| L1 — On-call | Any Soda check fails | Follow runbook, resolve within 30min |
| L2 — Senior Eng | Runbook steps don't resolve | Investigate root cause, check API status |
| L3 — Platform | DuckDB corruption, Airflow crash | Restore from backup, rebuild venv |

### Contact Points

| Exchange | Status Page | Support |
|----------|-----------|---------|
| Binance | https://www.binance.com/en/support | @BinanceHelpDesk (Twitter) |
| Bybit | No public status page | https://www.bybit.com/en/help-center |
| OKX | No public status page | https://www.okx.com/help-center |
