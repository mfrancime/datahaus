# datahaus Architecture

## Five-layer design

```
┌─────────────────────────────────────────────────────┐
│  Layer 5: Operations & Simulation                   │
│  Chaos Engine (Phase 3) │ Shift Console (Phase 3)   │
│  Runbooks │ Chaos Scripts (Phase 1+2)               │
├─────────────────────────────────────────────────────┤
│  Layer 4: Observability                             │
│  Soda Core checks │ Alert Router │ alert_log.jsonl  │
│  Optional: Slack webhook                            │
├─────────────────────────────────────────────────────┤
│  Layer 3: Storage                                   │
│  DuckDB │ Delta Lake tables                         │
│  Schemas: raw → staging → curated                   │
│  Unified table: curated.btc_ohlcv (exchange col)    │
├─────────────────────────────────────────────────────┤
│  Layer 2: Ingestion & Transformation                │
│  Apache Airflow DAGs │ Exchange Adapters             │
│  Reconciliation DAG                                 │
├─────────────────────────────────────────────────────┤
│  Layer 1: External Sources                          │
│  Binance (Phase 1) │ Bybit, OKX (Phase 2)          │
│  Polymarket (Phase 4)                               │
└─────────────────────────────────────────────────────┘
```

## Phase 2 data flow

```
Binance REST API ───┐
Bybit v5 API ───────┤
OKX v5 API ─────────┘
        │
        ▼
  Exchange Adapters (compute/adapters/)
  ┌──────────────────────────┐
  │ BinanceAdapter           │
  │ BybitAdapter             │
  │ OKXAdapter               │
  │ (ABC: fetch + transform) │
  └──────────────────────────┘
        │
        ▼
  Airflow DAGs (1 per exchange, */5 * * * *)
  ┌────────────────────────────┐
  │ extract  → raw JSON        │
  │ transform → unified dicts  │
  │ load     → DuckDB          │
  └────────────────────────────┘
        │
        ▼
  DuckDB (curated.btc_ohlcv)
  PK: (exchange, open_time)
        │
        ├──→ Soda Core checks (per-exchange + global)
        │    ├── freshness(ingested_at) < 10m
        │    ├── row_count > 0
        │    ├── duplicate_count(exchange, open_time) = 0
        │    └── exchange-specific field checks
        │
        └──→ Reconciliation DAG (2-57/5 * * * *)
             ├── detect_spread_anomalies (>1% threshold)
             └── route_alert → alert_log.jsonl [+ Slack]
```

## Unified table design

```sql
curated.btc_ohlcv
├── exchange        VARCHAR NOT NULL    -- PK part 1
├── open_time       BIGINT NOT NULL     -- PK part 2 (Unix ms)
├── open, high, low, close, volume      -- Common fields
├── close_time      BIGINT              -- Binance only (nullable)
├── quote_volume    DOUBLE              -- Binance + Bybit (nullable)
├── trade_count     INTEGER             -- Binance only (nullable)
├── taker_buy_*     DOUBLE              -- Binance only (nullable)
├── confirm         BOOLEAN             -- OKX only (nullable)
└── ingested_at     TIMESTAMP NOT NULL
```

## Key design decisions

- **DuckDB over Postgres:** Zero-ops, embedded, fast analytical queries. Right choice for a single-node platform.
- **Unified table with exchange column:** Single-scan reconciliation queries, no JOINs needed. PK = `(exchange, open_time)`.
- **Nullable exchange-specific fields:** Preserves Binance-specific data (close_time, trade_count, taker volumes) without inventing values for Bybit/OKX.
- **One DAG per exchange:** Independent pause/trigger/chaos per exchange. Simpler debugging than parametrized DAGs.
- **Exchange adapter ABC:** Clean separation of API-specific logic. Adding a new exchange = one new adapter + one new DAG.
- **Alert router (file + Slack):** Always logs to JSONL (zero external deps). Optional Slack via `SLACK_WEBHOOK_URL` env var.
- **Airflow standalone:** SequentialExecutor + SQLite metadata. Adequate for multi-pipeline workloads at this scale.
- **Soda Core:** Declarative data quality checks per exchange partition. Integrates with DuckDB natively.
