# Phase 2 Acceptance Criteria

**Date:** 2026-04-26
**Status:** Implementation complete — pending live verification

## Deliverables

### Schema migration
- [x] `exchange VARCHAR NOT NULL` column added
- [x] PK changed to `(exchange, open_time)`
- [x] Binance-specific fields made nullable (close_time, quote_volume, trade_count, taker_buy_*)
- [x] `confirm BOOLEAN` added for OKX
- [x] `make db-migrate` backfills existing rows with `exchange='binance'`

### Exchange adapters
- [x] ABC in `compute/adapters/base.py`
- [x] `BinanceAdapter` — wraps existing transform + adds exchange field
- [x] `BybitAdapter` — v5 API, 7-field format, newest-first→reverse
- [x] `OKXAdapter` �� v5 API, 9-field format, confirm flag, newest-first→reverse
- [x] All output unified dict format

### Reconciliation
- [x] `detect_spread_anomalies()` — groups by open_time, compares all exchange pairs
- [x] `summarize_anomalies()` — human-readable alert text
- [x] Default threshold: 1%

### Alert router
- [x] Always writes to `observability/alerts/alert_log.jsonl`
- [x] Optional Slack via `SLACK_WEBHOOK_URL` env var
- [x] Structured JSONL records with timestamp, check, exchange, outcome

### DAGs
- [x] Binance DAG updated — exchange-scoped DELETE + new column INSERT
- [x] Bybit DAG — same ETL pattern, */5 schedule
- [x] OKX DAG — same ETL pattern, */5 schedule
- [x] Reconciliation DAG — 2-57/5 schedule (offset from ingestion)

### Soda checks
- [x] `btc_ohlcv.yml` — global: row_count, duplicate_count(exchange, open_time)
- [x] `binance_ohlcv.yml` — freshness, row_count, duplicates, Binance fields NOT NULL
- [x] `bybit_ohlcv.yml` �� freshness, row_count, duplicates
- [x] `okx_ohlcv.yml` — freshness, row_count, duplicates, confirm NOT NULL

### Chaos scripts
- [x] `chaos_freshness.py` — `--exchange {binance,bybit,okx,all}` support
- [x] `chaos_clear.py` — `--exchange {binance,bybit,okx,all}` support
- [x] `chaos_spread.py` — inject/clean fake price anomaly

### Tests
- [x] `test_adapters.py` — 22 tests across 3 adapters (transform only)
- [x] `test_reconciliation.py` — 10 tests for spread detection + summary
- [x] All 37 tests passing

### Runbooks
- [x] RB-02: Bybit freshness
- [x] RB-03: OKX freshness
- [x] RB-04: Spread divergence

### Docs & Makefile
- [x] 18 new Makefile targets
- [x] Architecture doc updated with Phase 2 flow
- [x] README updated with Phase 2 instructions + roadmap

## Verification steps

```bash
make db-migrate           # migrate existing data
make test                 # 37 tests pass
make airflow-init && make airflow   # start Airflow
make trigger-all          # trigger all 3 exchange DAGs
make db-query-all         # verify rows from binance, bybit, okx
make run-checks-all       # Soda checks pass
make run-reconciliation   # reconciliation runs
make chaos-spread && make run-reconciliation && make view-alerts  # spread alert fires
make chaos-spread-clean   # clean up
```
