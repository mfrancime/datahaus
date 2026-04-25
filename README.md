# datahaus

A reference implementation of 24/7 market data operations using cryptocurrency feeds — chosen because they offer publicly-available, license-free, multi-source data with realistic operational characteristics (high velocity, strict freshness requirements, cross-source reconciliation needs).

datahaus demonstrates what production data operations looks like: automated ingestion, data quality monitoring, incident detection, chaos testing, and runbook-driven response — the daily work of a Data Operations team.

## Architecture

<!-- TODO: replace with SVG diagram -->
See [docs/architecture.md](docs/architecture.md) for the five-layer design.

**Phase 1 pipeline:**
```
Binance API → Airflow DAG → PySpark transform → DuckDB → Soda checks
```

## Quickstart

**Prerequisites:** Ubuntu/WSL2, Python 3.10+, Java 17+, `make`

```bash
git clone <repo-url> ~/datahaus && cd ~/datahaus

# One-time setup
make setup              # install Python dependencies
make airflow-init       # initialize Airflow DB + admin user

# Terminal 1: start Airflow
make airflow            # scheduler + webserver on :8080

# Terminal 2: operate the pipeline
make trigger-pipeline   # trigger the Binance ingestion DAG
                        # wait ~1 min for completion
make run-checks         # run Soda data quality checks (all should pass)

# Chaos testing
make chaos-freshness    # pause the DAG (simulates pipeline stall)
# wait for freshness threshold to expire, then:
make run-checks         # freshness check now FAILS

# Recovery
make chaos-clear        # un-pause the DAG
make trigger-pipeline   # ingest fresh data
make run-checks         # all checks pass again
```

## Make targets

| Target | Description |
|--------|-------------|
| `make setup` | Install system + Python dependencies |
| `make airflow-init` | Initialize Airflow DB and admin user |
| `make airflow` | Start Airflow standalone (scheduler + webserver) |
| `make trigger-pipeline` | Trigger the Binance klines DAG |
| `make run-checks` | Run Soda data quality checks |
| `make chaos-freshness` | Chaos: pause DAG to cause freshness breach |
| `make chaos-clear` | Recovery: un-pause DAG |
| `make test` | Run unit tests |
| `make db-query` | Show latest data in the warehouse |
| `make help` | List all targets |

## Tech stack

| Component | Tool |
|-----------|------|
| Orchestration | Apache Airflow (standalone) |
| Compute | PySpark (local mode) |
| Storage | DuckDB + Delta Lake |
| Data quality | Soda Core |
| Chaos scripts | Python + Airflow REST API |

## Phase roadmap

- **Phase 1** *(current)*: Single pipeline end-to-end — Binance BTC/USDT klines → DuckDB → Soda checks → manual chaos
- **Phase 2**: Multi-exchange (Coinbase, Kraken), cross-exchange reconciliation, alert router + Slack
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
