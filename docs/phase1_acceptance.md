# Phase 1 Acceptance Criteria

## What was built

- [x] Binance BTC/USDT 1-minute klines ingestion pipeline (Airflow DAG)
- [x] PySpark transform with typed output (`compute/ingest_klines.py`)
- [x] DuckDB warehouse with curated schema (`warehouse/schema.sql`)
- [x] Soda Core data quality checks — freshness, row count, duplicates
- [x] Chaos injection scripts — pause/unpause DAG via Airflow REST API
- [x] Runbook for freshness alert response (`runbooks/RB-01-binance-freshness.md`)
- [x] Makefile with all operational targets
- [x] Unit tests for the transform function (5 tests)

## Acceptance test results

All tests executed 2026-04-26.

| Step | Command | Result |
|------|---------|--------|
| Setup | `make setup` | Dependencies installed (Airflow 2.10.5, PySpark 3.5.4, DuckDB 1.0.0, Soda Core 3.5.6) |
| Airflow init | `make airflow-init` | DB migrated, admin user created |
| Airflow start | `make airflow` | Standalone running on :8080 |
| Trigger pipeline | `make trigger-pipeline` | DAG triggered, completed in ~30s, 100 rows loaded |
| Run checks | `make run-checks` | 3/3 checks PASSED (freshness, row_count, duplicate_count) |
| Chaos inject | `make chaos-freshness` | DAG paused successfully |
| Run checks (fail) | `make run-checks` | 1/3 FAILED: freshness exceeded threshold (2m38s > 1m) |
| Chaos clear | `make chaos-clear` | DAG un-paused |
| Trigger recovery | `make trigger-pipeline` | Fresh data ingested |
| Run checks (pass) | `make run-checks` | 3/3 checks PASSED |
| Unit tests | `make test` | 5/5 passed |

## Deviations from briefing

1. **Java version:** Briefing specified Java 17. System had Java 25 (Homebrew). Java 17 installed alongside via apt; `JAVA_HOME` pinned to Java 17 in Makefile.
2. **DuckDB version:** Soda Core pinned duckdb to 1.0.0 (latest was 1.5.2). No functional impact.
3. **setuptools required:** Python 3.12 removed `distutils`. Soda Core depends on it. Added `setuptools` to provide the shim.
4. **Freshness threshold for demo:** Temporarily lowered to 1m during acceptance testing to avoid 10-minute wait. Restored to 10m after verification.
5. **PySpark usage:** The DAG uses `transform_klines()` (pure Python) for the actual transform rather than running a full Spark job. The Spark DataFrame variant (`transform_klines_spark()`) is available for testing and future batch paths. This keeps the DAG lightweight while still demonstrating Spark competency in the codebase.
6. **DAG auto-unpause:** Added an un-pause step to `make trigger-pipeline` since Airflow defaults new DAGs to paused state.

## Architecture notes

- Airflow standalone uses SequentialExecutor + SQLite — appropriate for single-pipeline Phase 1
- DuckDB is used directly (not via Delta Lake) for Phase 1 simplicity. Delta Lake integration available via `transform_klines_spark()` for Phase 2
- Soda checks run from project root; `configuration.yml` uses relative path to DuckDB file
