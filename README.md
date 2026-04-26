# datahaus

A reference implementation of 24/7 market data operations using cryptocurrency feeds — chosen because they offer publicly-available, license-free, multi-source data with realistic operational characteristics (high velocity, strict freshness requirements, cross-source reconciliation needs).

datahaus demonstrates what production data operations looks like: automated ingestion, data quality monitoring, incident detection, chaos testing, and runbook-driven response — the daily work of a Data Operations team.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the five-layer design.

**Phase 2 pipeline:**
```
Binance + Bybit + OKX APIs → Exchange Adapters → Airflow DAGs → DuckDB → Soda checks
                                                                   └──→ Reconciliation → Alert Router
```

## Quickstart

**Prerequisites:** Ubuntu/WSL2, Python 3.10+, Java 17+, `make`

```bash
git clone <repo-url> ~/datahaus && cd ~/datahaus

# One-time setup
make setup              # install Python dependencies
make airflow-init       # initialize Airflow DB + admin user
make db-init            # bootstrap DuckDB schema

# If upgrading from Phase 1:
make db-migrate         # migrate existing Binance data to new schema

# Terminal 1: start Airflow
make airflow            # scheduler + webserver on :8080

# Terminal 2: operate the pipelines
make trigger-all        # trigger all 3 exchange DAGs
                        # wait ~1-2 min for completion
make db-query-all       # verify data from all exchanges
make run-checks-all     # run Soda checks (all should pass)

# Reconciliation
make run-reconciliation # check for cross-exchange spread anomalies
make view-alerts        # view alert history

# Chaos testing — freshness
make chaos-freshness-bybit   # pause the Bybit DAG
# wait for freshness threshold to expire, then:
make run-checks-all          # Bybit freshness check FAILS
make chaos-clear ARGS="--exchange bybit"  # un-pause
make trigger-bybit           # ingest fresh data
make run-checks-all          # all checks pass again

# Chaos testing — spread divergence
make chaos-spread            # inject fake price anomaly
make run-reconciliation      # spread alert fires
make view-alerts             # see the alert
make chaos-spread-clean      # clean up injected data
```

## Make targets

| Target | Description |
|--------|-------------|
| **Setup** | |
| `make setup` | Install system + Python dependencies |
| `make airflow-init` | Initialize Airflow DB and admin user |
| `make db-init` | Bootstrap the DuckDB schema |
| `make db-migrate` | Migrate Phase 1 data to Phase 2 schema |
| **Run** | |
| `make airflow` | Start Airflow standalone (scheduler + webserver) |
| `make trigger-binance` | Trigger Binance klines DAG |
| `make trigger-bybit` | Trigger Bybit klines DAG |
| `make trigger-okx` | Trigger OKX klines DAG |
| `make trigger-all` | Trigger all exchange DAGs |
| `make run-reconciliation` | Trigger cross-exchange reconciliation |
| `make run-checks` | Run Soda checks (Binance + global) |
| `make run-checks-all` | Run Soda checks for all exchanges |
| **Chaos** | |
| `make chaos-freshness` | Pause Binance DAG (default) |
| `make chaos-freshness-bybit` | Pause Bybit DAG |
| `make chaos-freshness-okx` | Pause OKX DAG |
| `make chaos-freshness-all` | Pause all DAGs |
| `make chaos-spread` | Inject fake price anomaly |
| `make chaos-spread-clean` | Clean up spread chaos |
| `make chaos-clear` | Un-pause DAG(s) |
| **Dev** | |
| `make test` | Run unit tests |
| `make db-query` | Show latest Binance data |
| `make db-query-all` | Show data summary per exchange |
| `make view-alerts` | Show recent alerts |
| `make help` | List all targets |

## Tech stack

| Component | Tool |
|-----------|------|
| Orchestration | Apache Airflow (standalone) |
| Compute | Exchange adapters (pure Python) |
| Storage | DuckDB (unified table with exchange column) |
| Data quality | Soda Core (per-exchange + global checks) |
| Reconciliation | Cross-exchange spread detection |
| Alerting | File-based JSONL + optional Slack webhook |
| Chaos scripts | Python + Airflow REST API + DuckDB injection |

## Phase roadmap

- **Phase 1** *(complete)*: Single pipeline end-to-end — Binance BTC/USDT klines → DuckDB → Soda checks → manual chaos
- **Phase 2** *(complete)*: Multi-exchange (Bybit, OKX), cross-exchange reconciliation, alert router + Slack
- **Phase 3**: Chaos Engine framework, Shift Console UI, scripted failure scenarios
- **Phase 4**: Polymarket as second data domain, runbook library, demo video

## Why cryptocurrency data?

Crypto markets trade 24/7/365 with publicly-accessible APIs requiring no licensing or authentication. This provides:
- **Continuous data flow** for realistic operational monitoring
- **Multiple independent sources** (exchanges) for cross-source reconciliation
- **Real failure modes** (API rate limits, exchange outages, data gaps) that mirror enterprise data operations
- **Zero cost** — all APIs used are free public endpoints

The choice of data domain is incidental. The operational patterns — ingestion monitoring, freshness checks, incident response, chaos testing — are universal.

## License

MIT
