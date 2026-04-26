# datahaus Documentation Hub

All technical documentation for the datahaus platform. Start here to find what you need.

## Quick Navigation

| Document | Audience | Description |
|----------|----------|-------------|
| [Process Flow](process_flow.md) | All | End-to-end data flow, pipeline lifecycle, alert routing |
| [Operations Manual (MOP)](operations_manual.md) | Ops | Method of Procedure — daily operations, monitoring, incident response |
| [Developer Guide](developer_guide.md) | Dev | Architecture, adding exchanges, testing, schema design |
| [Architecture](architecture.md) | All | Five-layer design, key decisions, system diagrams |
| [Phase 1 Acceptance](phase1_acceptance.md) | All | Phase 1 deliverables and acceptance criteria |
| [Phase 2 Acceptance](phase2_acceptance.md) | All | Phase 2 deliverables and acceptance criteria |

## Runbooks (Incident Response)

| Runbook | Trigger | Severity |
|---------|---------|----------|
| [RB-01](../runbooks/RB-01-binance-freshness.md) | Binance freshness breach | P2 |
| [RB-02](../runbooks/RB-02-bybit-freshness.md) | Bybit freshness breach | P2 |
| [RB-03](../runbooks/RB-03-okx-freshness.md) | OKX freshness breach | P2 |
| [RB-04](../runbooks/RB-04-spread-divergence.md) | Cross-exchange spread divergence | P3 |

## System at a Glance

```
                     datahaus — Phase 2
  ┌─────────────────────────────────────────────┐
  │         3 Exchanges  ×  1-min candles       │
  │    Binance  ·  Bybit  ·  OKX               │
  │                                             │
  │    4 Airflow DAGs  ·  17 Soda checks        │
  │    1 Reconciliation pipeline                │
  │    Alert router (file + Slack)              │
  │    3 Chaos scripts  ·  4 Runbooks           │
  │    37 unit tests                            │
  └─────────────────────────────────────────────┘
```

## File Map

```
datahaus/
├── compute/
│   ├── adapters/           # Exchange-specific API + transform logic
│   │   ├── base.py         #   ABC: ExchangeAdapter
│   │   ├── binance.py      #   Binance v3 klines
│   │   ├── bybit.py        #   Bybit v5 klines
│   │   └── okx.py          #   OKX v5 candles
│   ├── ingest_klines.py    # Legacy Phase 1 transform (still used by tests)
│   └── reconciliation.py   # Cross-exchange spread detection
├── pipelines/
│   ├── binance_klines_1m.py    # Binance ETL DAG
│   ├── bybit_klines_1m.py     # Bybit ETL DAG
│   ├── okx_klines_1m.py       # OKX ETL DAG
│   └── reconciliation_dag.py  # Cross-exchange reconciliation DAG
├── warehouse/
│   └── schema.sql          # DuckDB DDL (curated.btc_ohlcv)
├── observability/
│   ├── alert_router.py     # File + Slack alert routing
│   ├── alerts/             # JSONL alert log output
│   └── soda_checks/        # Per-exchange + global Soda configs
├── scripts/
│   ├── chaos_freshness.py  # Pause DAGs (simulate stall)
│   ├── chaos_clear.py      # Un-pause DAGs (recovery)
│   ├── chaos_spread.py     # Inject fake price anomaly
│   └── migrate_phase2.py   # Phase 1 → Phase 2 schema migration
├── tests/                  # pytest unit tests
├── runbooks/               # Incident response procedures
├── docs/                   # This documentation
├── Makefile                # All operational targets
└── pyproject.toml          # Python project config
```
