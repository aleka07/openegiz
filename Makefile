.PHONY: up down ps logs smoke clean example-mine example-mine-stop install uninstall status endpoints upgrade upload-build generate-data copy-build check-secrets

# ---------------------------------------------------------------------------
# Docker Compose deployment (laptops, CI, contest judges): deploy/compose/
# ---------------------------------------------------------------------------
COMPOSE := docker compose -f deploy/compose/docker-compose.yml

## Start the whole platform with Docker Compose (first run: generates credentials)
up:
	@bash scripts/compose-env.sh
	@bash scripts/compose-preflight.sh
	$(COMPOSE) up -d --build --wait --wait-timeout 900
	@test "$$($(COMPOSE) ps -a --format '{{.ExitCode}}' init)" = 0 || { \
	  echo "ERROR: the init job (policy + Ditto connections) failed:"; $(COMPOSE) logs init; exit 1; }
	@bash scripts/compose-wait-ready.sh
	@bash scripts/compose-urls.sh

## Stop the platform, keep data
down:
	$(COMPOSE) down

## Show compose service status
ps:
	@$(COMPOSE) ps -a

## Follow logs (one service: make logs S=gateway)
logs:
	$(COMPOSE) logs -f --tail=100 $(S)

## End-to-end check of the running compose stack
smoke:
	@bash scripts/compose-smoke.sh

## Run the Example Mine (twins + haul-cycle simulator + Grafana dashboard) on the compose stack
example-mine: up
	$(COMPOSE) -f examples/mine/compose.yml up -d --build --wait --wait-timeout 300
	@echo "Example Mine running: Grafana -> Dashboards -> OpenEgiz -> Example Mine"

## Stop the Example Mine simulator (twins and data stay)
example-mine-stop:
	$(COMPOSE) -f examples/mine/compose.yml stop mine-simulator

## Stop the platform and DELETE all its data and credentials
clean:
	$(COMPOSE) down -v --remove-orphans
	rm -f deploy/compose/.env

# ---------------------------------------------------------------------------
# Helm deployment (servers): the chart at the repository root
# ---------------------------------------------------------------------------
# Several values reference names derived from the release name (e.g. the
# telegraf configmap), so the release MUST be called "opentwins" until those
# references are made release-agnostic.
RELEASE_NAME := opentwins
NAMESPACE    := opentwins
CHART_PATH   := .

# Credentials live OUTSIDE this repo (rotated 2026-08-07). values.yaml carries
# only invalid placeholders, so install/upgrade must always be given this
# override file. Deliberately a hard failure rather than a silent fallback:
# deploying the placeholders would break Ditto auth and telemetry ingest.
SECRETS_FILE ?= $(HOME)/openegiz-deploy/secrets.values.yaml

check-secrets:
	@test -f "$(SECRETS_FILE)" || { \
	  echo "ERROR: secrets override not found: $(SECRETS_FILE)"; \
	  echo "       It holds the Ditto/Grafana/InfluxDB credentials that are"; \
	  echo "       intentionally absent from values.yaml. See ~/course/CREDENTIALS.md"; \
	  echo "       on the host, or override with: make upgrade SECRETS_FILE=/path/to/file"; \
	  exit 1; }

## Install the OpenEgiz Helm chart
install: check-secrets
	helm install $(RELEASE_NAME) $(CHART_PATH) -n $(NAMESPACE) --create-namespace -f "$(SECRETS_FILE)" --wait --timeout=15m --debug

## Upgrade the OpenEgiz Helm chart
upgrade: check-secrets
	helm upgrade $(RELEASE_NAME) $(CHART_PATH) -n $(NAMESPACE) -f "$(SECRETS_FILE)" --wait --timeout=15m --debug

## Uninstall the OpenEgiz Helm chart
uninstall:
	helm uninstall $(RELEASE_NAME) -n $(NAMESPACE) --wait

## Show pod statuses
status:
	@kubectl get pods -n $(NAMESPACE) -o wide

## Show all service endpoints (IP + port)
endpoints:
	@bash scripts/show-endpoints.sh

## Upload Unity WebGL build files to the nginx pod
upload-build:
	@bash scripts/upload-build.sh $(RELEASE_NAME)

## Run the data generator for oven twins
generate-data:
	@bash -c 'source data-generator/venv/bin/activate && python3 data-generator/data_generator.py'

## Copy 4 Unity WebGL build files from SRC into ./build/
## Usage: make copy-build SRC=/path/to/source
copy-build:
	@bash scripts/copy-build.sh $(SRC)
