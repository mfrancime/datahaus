# datahaus Operations Quick Reference

One-page operational reference for the datahaus platform. For full documentation, see [`docs/`](docs/README.md).

---

## System Status Check

```bash
make db-query-all       # row counts + latest per exchange
make run-checks-all     # 17 Soda data quality checks
make view-alerts        # recent alert history
```

---

## Architecture

```
Binance API ──→ BinanceAdapter ──→ Airflow DAG ──→ DuckDB ──→ Soda checks
Bybit API   ──→ BybitAdapter   ──→ Airflow DAG ──→   ↓    ──→ Soda checks
OKX API     ──→ OKXAdapter     ──→ Airflow DAG ──→   ↓    ──→ Soda checks
                                                      ↓
                                            Reconciliation DAG
                                                      ↓
                                               Alert Router
                                           ┌────────────────┐
                                           │ alert_log.jsonl │
                                           │ Slack (optional)│
                                           └────────────────┘
```

**Storage:** DuckDB `curated.btc_ohlcv` — unified table, PK = `(exchange, open_time)`

**Schedule:** All exchange DAGs `*/5 * * * *` | Reconciliation `2-57/5 * * * *`

---

## Pipeline Inventory

| DAG | Source | Schedule | Retries |
|-----|--------|----------|---------|
| `binance_klines_1m` | Binance REST v3 | Every 5 min | 3 |
| `bybit_klines_1m` | Bybit REST v5 | Every 5 min | 3 |
| `okx_klines_1m` | OKX REST v5 | Every 5 min | 3 |
| `reconciliation` | Internal (DuckDB) | Every 5 min (+2 offset) | 1 |

---

## Soda Check Summary (17 total)

| Scope | Checks | What's Validated |
|-------|--------|-----------------|
| Global | 2 | row_count > 0, no PK duplicates |
| Binance | 8 | freshness, rows, dupes, 5 NOT NULL fields |
| Bybit | 3 | freshness, rows, dupes |
| OKX | 4 | freshness, rows, dupes, confirm NOT NULL |

---

## Make Targets

### Operate
```bash
make airflow            # start Airflow (:8080)
make trigger-binance    # trigger single exchange
make trigger-all        # trigger all 3 exchanges
make run-reconciliation # run cross-exchange checks
make run-checks-all     # run all Soda checks
make db-query-all       # data summary per exchange
make view-alerts        # recent alert log
```

### Chaos Test
```bash
make chaos-freshness               # pause Binance DAG
make chaos-freshness-bybit         # pause Bybit DAG
make chaos-freshness-okx           # pause OKX DAG
make chaos-freshness-all           # pause all DAGs
make chaos-spread                  # inject +5% fake price
make chaos-clear ARGS="--exchange all"  # un-pause all
make chaos-spread-clean            # remove fake data
```

### Develop
```bash
make test               # run 37 unit tests
make db-init            # bootstrap schema
make db-migrate         # Phase 1 → Phase 2 migration
make setup              # install dependencies
make airflow-init       # init Airflow DB
```

---

## Incident Response

| Alert | Severity | Runbook | Quick Fix |
|-------|----------|---------|-----------|
| Binance freshness | P2 | [RB-01](runbooks/RB-01-binance-freshness.md) | `make chaos-clear && make trigger-binance` |
| Bybit freshness | P2 | [RB-02](runbooks/RB-02-bybit-freshness.md) | `make chaos-clear ARGS="--exchange bybit" && make trigger-bybit` |
| OKX freshness | P2 | [RB-03](runbooks/RB-03-okx-freshness.md) | `make chaos-clear ARGS="--exchange okx" && make trigger-okx` |
| Spread divergence | P3 | [RB-04](runbooks/RB-04-spread-divergence.md) | Check for chaos injection first |

### Emergency Recovery

```bash
# Un-pause everything and re-ingest
make chaos-clear ARGS="--exchange all"
make trigger-all
sleep 120
make run-checks-all     # verify all 17 pass
```

---

## API Endpoints Used

| Exchange | Endpoint | Auth | Rate Limit |
|----------|----------|------|-----------|
| Binance | `api.binance.com/api/v3/klines` | Public | 1200 req/min |
| Bybit | `api.bybit.com/v5/market/kline` | Public | 600 req/5s |
| OKX | `www.okx.com/api/v5/market/candles` | Public | 40 req/2s |

---

## Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `SLACK_WEBHOOK_URL` | Slack alert webhook | None (file-only) |
| `AIRFLOW_HOME` | Airflow metadata | `.airflow/` |
| `JAVA_HOME` | JVM for PySpark | `/usr/lib/jvm/java-17-openjdk-amd64` |

---

## Documentation Map

| Doc | Path | Audience |
|-----|------|----------|
| **This file** | `OPERATIONS.md` | Quick reference |
| Docs hub | [`docs/README.md`](docs/README.md) | All |
| Process flow | [`docs/process_flow.md`](docs/process_flow.md) | All |
| Operations manual | [`docs/operations_manual.md`](docs/operations_manual.md) | Ops |
| Developer guide | [`docs/developer_guide.md`](docs/developer_guide.md) | Dev |
| Architecture | [`docs/architecture.md`](docs/architecture.md) | All |

---

## Phase Roadmap

- **Phase 1** (complete): Binance single pipeline
- **Phase 2** (complete): Multi-exchange (Bybit, OKX) + reconciliation + alert router
- **Phase 3** (planned): Chaos Engine framework, Shift Console UI
- **Phase 4** (planned): Polymarket data domain, demo video
