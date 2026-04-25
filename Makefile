# datahaus — Phase 1 Makefile
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

DAG_ID := binance_klines_1m

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

.PHONY: trigger-pipeline
trigger-pipeline: ## Trigger the Binance klines DAG manually
	@echo "==> Ensuring DAG '$(DAG_ID)' is un-paused..."
	@curl -s -X PATCH \
		-u admin:admin \
		-H "Content-Type: application/json" \
		-d '{"is_paused": false}' \
		"http://localhost:8080/api/v1/dags/$(DAG_ID)" > /dev/null
	@echo "==> Triggering DAG '$(DAG_ID)'..."
	@curl -s -X POST \
		-u admin:admin \
		-H "Content-Type: application/json" \
		-d '{}' \
		"http://localhost:8080/api/v1/dags/$(DAG_ID)/dagRuns" | $(PYTHON) -m json.tool
	@echo ""
	@echo "==> DAG triggered. Monitor at http://localhost:8080 or wait ~1 min."

.PHONY: run-checks
run-checks: ## Run Soda data quality checks
	@echo "==> Running Soda checks on curated.btc_ohlcv..."
	cd $(CURDIR) && $(SODA) scan \
		-d datahaus \
		-c observability/soda_checks/configuration.yml \
		observability/soda_checks/btc_ohlcv.yml

# ──────────────────────────────────────────────
# Chaos targets
# ──────────────────────────────────────────────

.PHONY: chaos-freshness
chaos-freshness: ## Inject failure: pause the DAG to cause freshness breach
	$(PYTHON) scripts/chaos_freshness.py

.PHONY: chaos-clear
chaos-clear: ## Recovery: un-pause the DAG
	$(PYTHON) scripts/chaos_clear.py

# ──────────────────────────────────────────────
# Dev targets
# ──────────────────────────────────────────────

.PHONY: test
test: ## Run unit tests
	$(PYTHON) -m pytest tests/ -v

.PHONY: db-query
db-query: ## Quick check: show latest rows in curated.btc_ohlcv
	@$(PYTHON) -c "\
import duckdb; \
con = duckdb.connect('warehouse/datahaus.duckdb', read_only=True); \
print(con.execute('SELECT COUNT(*) as total, MAX(ingested_at) as latest FROM curated.btc_ohlcv').fetchdf().to_string()); \
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

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
