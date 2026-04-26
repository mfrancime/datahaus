# datahaus — Phase 2 Makefile
# All targets assume the venv exists at ~/.venvs/datahaus

SHELL := /bin/bash
VENV := $(HOME)/.venvs/datahaus/bin
PYTHON := $(VENV)/python
PIP := $(VENV)/pip
AIRFLOW := $(VENV)/airflow
SODA := $(VENV)/soda

export AIRFLOW_HOME := $(CURDIR)/.airflow
export AIRFLOW__CORE__DAGS_FOLDER := $(CURDIR)/pipelines
export AIRFLOW__CORE__LOAD_EXAMPLES := False
export JAVA_HOME := /usr/lib/jvm/java-17-openjdk-amd64
# Airflow standalone spawns subprocesses that need 'airflow' on PATH
export PATH := $(VENV):$(PATH)

# ──────────────────────────────────────────────
# Setup targets (run once)
# ──────────────────────────────────────────────

.PHONY: setup
setup: ## Install system deps + Python packages
	@echo "==> Checking system dependencies..."
	@which java >/dev/null 2>&1 || (echo "ERROR: Java not found. Install openjdk-17-jre-headless" && exit 1)
	@echo "==> Creating venv (if needed)..."
	@test -d $(HOME)/.venvs/datahaus || python3 -m venv $(HOME)/.venvs/datahaus
	@echo "==> Installing Python packages..."
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet "apache-airflow==2.10.5" \
		--constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.12.txt"
	$(PIP) install --quiet pyspark==3.5.4 delta-spark==3.3.0 duckdb requests pandas python-dotenv pytest \
		soda-core soda-core-duckdb
	@echo "==> Setup complete."

.PHONY: airflow-init
airflow-init: ## Initialize Airflow DB + create admin user
	@echo "==> Migrating Airflow metadata DB..."
	$(AIRFLOW) db migrate
	@echo "==> Creating admin user..."
	$(AIRFLOW) users create \
		--username admin --password admin \
		--firstname Admin --lastname User \
		--role Admin --email admin@datahaus.local 2>/dev/null || true
	@echo "==> Airflow initialized. UI will be at http://localhost:8080"

# ──────────────────────────────────────────────
# Run targets
# ──────────────────────────────────────────────

.PHONY: airflow
airflow: ## Start Airflow standalone (scheduler + webserver)
	@echo "==> Starting Airflow standalone on :8080..."
	@echo "==> Press Ctrl+C to stop"
	$(AIRFLOW) standalone

.PHONY: trigger-binance
trigger-binance: ## Trigger the Binance klines DAG
	@echo "==> Triggering binance_klines_1m..."
	@curl -s -X PATCH -u admin:admin -H "Content-Type: application/json" \
		-d '{"is_paused": false}' "http://localhost:8080/api/v1/dags/binance_klines_1m" > /dev/null
	@curl -s -X POST -u admin:admin -H "Content-Type: application/json" \
		-d '{}' "http://localhost:8080/api/v1/dags/binance_klines_1m/dagRuns" | $(PYTHON) -m json.tool

.PHONY: trigger-bybit
trigger-bybit: ## Trigger the Bybit klines DAG
	@echo "==> Triggering bybit_klines_1m..."
	@curl -s -X PATCH -u admin:admin -H "Content-Type: application/json" \
		-d '{"is_paused": false}' "http://localhost:8080/api/v1/dags/bybit_klines_1m" > /dev/null
	@curl -s -X POST -u admin:admin -H "Content-Type: application/json" \
		-d '{}' "http://localhost:8080/api/v1/dags/bybit_klines_1m/dagRuns" | $(PYTHON) -m json.tool

.PHONY: trigger-okx
trigger-okx: ## Trigger the OKX klines DAG
	@echo "==> Triggering okx_klines_1m..."
	@curl -s -X PATCH -u admin:admin -H "Content-Type: application/json" \
		-d '{"is_paused": false}' "http://localhost:8080/api/v1/dags/okx_klines_1m" > /dev/null
	@curl -s -X POST -u admin:admin -H "Content-Type: application/json" \
		-d '{}' "http://localhost:8080/api/v1/dags/okx_klines_1m/dagRuns" | $(PYTHON) -m json.tool

.PHONY: trigger-pipeline
trigger-pipeline: trigger-binance ## Trigger Binance DAG (Phase 1 compat alias)

.PHONY: trigger-all
trigger-all: ## Trigger all exchange DAGs
	@$(MAKE) trigger-binance
	@$(MAKE) trigger-bybit
	@$(MAKE) trigger-okx

.PHONY: run-reconciliation
run-reconciliation: ## Trigger the reconciliation DAG
	@echo "==> Triggering reconciliation..."
	@curl -s -X PATCH -u admin:admin -H "Content-Type: application/json" \
		-d '{"is_paused": false}' "http://localhost:8080/api/v1/dags/reconciliation" > /dev/null
	@curl -s -X POST -u admin:admin -H "Content-Type: application/json" \
		-d '{}' "http://localhost:8080/api/v1/dags/reconciliation/dagRuns" | $(PYTHON) -m json.tool

.PHONY: run-checks
run-checks: ## Run Soda checks (Binance only — Phase 1 compat)
	@echo "==> Running Soda checks on curated.btc_ohlcv (global + Binance)..."
	cd $(CURDIR) && $(SODA) scan \
		-d datahaus \
		-c observability/soda_checks/configuration.yml \
		observability/soda_checks/btc_ohlcv.yml \
		observability/soda_checks/binance_ohlcv.yml

.PHONY: run-checks-all
run-checks-all: ## Run Soda checks for all exchanges
	@echo "==> Running Soda checks on all exchanges..."
	cd $(CURDIR) && $(SODA) scan \
		-d datahaus \
		-c observability/soda_checks/configuration.yml \
		observability/soda_checks/btc_ohlcv.yml \
		observability/soda_checks/binance_ohlcv.yml \
		observability/soda_checks/bybit_ohlcv.yml \
		observability/soda_checks/okx_ohlcv.yml

# ──────────────────────────────────────────────
# Chaos targets
# ──────────────────────────────────────────────

.PHONY: chaos-freshness
chaos-freshness: ## Inject failure: pause a DAG (default: binance)
	$(PYTHON) scripts/chaos_freshness.py $(ARGS)

.PHONY: chaos-freshness-bybit
chaos-freshness-bybit: ## Inject failure: pause the Bybit DAG
	$(PYTHON) scripts/chaos_freshness.py --exchange bybit

.PHONY: chaos-freshness-okx
chaos-freshness-okx: ## Inject failure: pause the OKX DAG
	$(PYTHON) scripts/chaos_freshness.py --exchange okx

.PHONY: chaos-freshness-all
chaos-freshness-all: ## Inject failure: pause all exchange DAGs
	$(PYTHON) scripts/chaos_freshness.py --exchange all

.PHONY: chaos-spread
chaos-spread: ## Inject failure: fake price anomaly for spread detection
	$(PYTHON) scripts/chaos_spread.py

.PHONY: chaos-spread-clean
chaos-spread-clean: ## Clean up spread chaos injection
	$(PYTHON) scripts/chaos_spread.py --clean

.PHONY: chaos-clear
chaos-clear: ## Recovery: un-pause DAG(s) (default: binance)
	$(PYTHON) scripts/chaos_clear.py $(ARGS)

# ──────────────────────────────────────────────
# Dev targets
# ──────────────────────────────────────────────

.PHONY: test
test: ## Run unit tests
	$(PYTHON) -m pytest tests/ -v

.PHONY: db-migrate
db-migrate: ## Migrate existing Binance data to Phase 2 schema (adds exchange column)
	$(PYTHON) scripts/migrate_phase2.py

.PHONY: db-query
db-query: ## Quick check: show latest Binance rows
	@$(PYTHON) -c "\
import duckdb; \
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True); \
print(con.execute(\"SELECT COUNT(*) as total, MAX(ingested_at) as latest FROM curated.btc_ohlcv WHERE exchange = 'binance'\").fetchdf().to_string()); \
con.close()"

.PHONY: db-query-all
db-query-all: ## Show row counts and latest ingestion per exchange
	@$(PYTHON) -c "\
import duckdb; \
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True); \
print(con.execute('SELECT exchange, COUNT(*) as rows, MAX(ingested_at) as latest FROM curated.btc_ohlcv GROUP BY exchange ORDER BY exchange').fetchdf().to_string()); \
con.close()"

.PHONY: db-init
db-init: ## Bootstrap the DuckDB schema
	@echo "==> Initializing DuckDB schema..."
	@$(PYTHON) -c "\
import duckdb; \
from pathlib import Path; \
con = duckdb.connect('warehouse/datahaus.duckdb'); \
sql = Path('warehouse/schema.sql').read_text(); \
[con.execute(s.strip()) for s in sql.split(';') if s.strip()]; \
con.close(); \
print('Schema initialized.')"

.PHONY: view-alerts
view-alerts: ## Show recent alerts from the alert log
	@echo "==> Recent alerts:"
	@if [ -f observability/alerts/alert_log.jsonl ]; then \
		tail -20 observability/alerts/alert_log.jsonl | $(PYTHON) -m json.tool --no-ensure-ascii; \
	else \
		echo "No alerts yet."; \
	fi

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
