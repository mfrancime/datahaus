# datahaus Architecture

## Five-layer design

```
┌─────────────────────────────────────────────────────┐
│  Layer 5: Operations & Simulation                   │
│  Chaos Engine (Phase 3) │ Shift Console (Phase 3)   │
│  Runbooks │ Chaos Scripts (Phase 1)                  │
├─────────────────────────────────────────────────────┤
│  Layer 4: Observability                             │
│  Soda Core checks │ Alert Router (Phase 2)          │
├─────────────────────────────────────────────────────┤
│  Layer 3: Storage                                   │
│  DuckDB │ Delta Lake tables                         │
│  Schemas: raw → staging → curated                   │
├─────────────────────────────────────────────────────┤
│  Layer 2: Ingestion & Transformation                │
│  Apache Airflow DAGs │ PySpark transforms           │
├─────────────────────────────────────────────────────┤
│  Layer 1: External Sources                          │
│  Binance (Phase 1) │ Coinbase, Kraken (Phase 2)    │
│  Polymarket (Phase 4)                               │
└─────────────────────────────────────────────────────┘
```

## Phase 1 data flow

```
Binance REST API (/api/v3/klines)
        │
        ▼
  Airflow DAG (binance_klines_1m)
  ┌─────────────────────┐
  │ extract  → raw JSON │
  │ transform → typed   │
  │ load     → DuckDB   │
  └─────────────────────┘
        │
        ▼
  DuckDB (curated.btc_ohlcv)
        │
        ▼
  Soda Core checks
  ├── freshness(ingested_at) < 10m
  ├── row_count > 0
  └── duplicate_count(open_time) = 0
```

## Key design decisions

- **DuckDB over Postgres:** Zero-ops, embedded, fast analytical queries. Right choice for a single-node platform.
- **PySpark in local mode:** Demonstrates Spark competency without cluster overhead. Trivial to point at a cluster later.
- **Airflow standalone:** SequentialExecutor + SQLite metadata. Adequate for single-pipeline workloads.
- **Soda Core:** Declarative data quality checks. Integrates with DuckDB natively.
