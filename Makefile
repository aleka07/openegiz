.PHONY: up down ps logs smoke clean example-mine example-mine-stop install uninstall status endpoints upgrade upload-build generate-data copy-build check-secrets check-public-host

# ---------------------------------------------------------------------------
# Docker Compose deployment (laptops, CI, contest judges): deploy/compose/
# ---------------------------------------------------------------------------
COMPOSE_BASE := docker compose -f deploy/compose/docker-compose.yml
# Once `make example-mine` has run, every compose command also loads the mine
# overlay, so `down` stops its simulator and `up` keeps its Grafana dashboard.
# `make clean` forgets it.
MINE_MARKER  := deploy/compose/.example-mine
MINE_COMPOSE := examples/mine/compose.yml
COMPOSE := $(COMPOSE_BASE)$(if $(wildcard $(MINE_MARKER)), -f $(MINE_COMPOSE))

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
	$(COMPOSE_BASE) -f $(MINE_COMPOSE) up -d --build --wait --wait-timeout 300
	@touch $(MINE_MARKER)
	@echo "Example Mine running: Grafana -> Dashboards -> OpenEgiz Examples -> Example Mine"

## Stop the Example Mine simulator (twins and data stay)
example-mine-stop:
	$(COMPOSE_BASE) -f $(MINE_COMPOSE) stop mine-simulator

## Stop the platform and DELETE all its data and credentials
clean:
	$(COMPOSE) down -v --remove-orphans
	rm -f deploy/compose/.env $(MINE_MARKER)

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

# Address browsers use to reach this host; the Grafana app plugin calls Ditto
# and the extended API from the browser. Defaults to the first node's
# InternalIP; override with `make install PUBLIC_HOST=my-host.example`.
PUBLIC_HOST ?= $(shell kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null)

check-public-host:
	@test -n "$(PUBLIC_HOST)" || { \
	  echo "ERROR: could not determine PUBLIC_HOST from kubectl."; \
	  echo "       Pass it explicitly: make install PUBLIC_HOST=<ip-or-hostname>"; \
	  exit 1; }

check-secrets:
	@test -f "$(SECRETS_FILE)" || { \
	  echo "ERROR: secrets override not found: $(SECRETS_FILE)"; \
	  echo "       It holds the Ditto/Grafana/InfluxDB credentials that are"; \
	  echo "       intentionally absent from values.yaml. Create it from"; \
	  echo "       secrets.values.yaml.example, or point to another file with:"; \
	  echo "       make install SECRETS_FILE=/path/to/file"; \
	  exit 1; }

## Install the OpenEgiz Helm chart
install: check-secrets check-public-host
	helm install $(RELEASE_NAME) $(CHART_PATH) -n $(NAMESPACE) --create-namespace -f "$(SECRETS_FILE)" --set grafanaPlugin.publicHost=$(PUBLIC_HOST) --wait --timeout=15m --debug

## Upgrade the OpenEgiz Helm chart
upgrade: check-secrets check-public-host
	helm upgrade $(RELEASE_NAME) $(CHART_PATH) -n $(NAMESPACE) -f "$(SECRETS_FILE)" --set grafanaPlugin.publicHost=$(PUBLIC_HOST) --wait --timeout=15m --debug

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

## Oven demo: create the oven twins, then stream telemetry (Ctrl+C to stop).
## Compose by default; Helm: make generate-data MQTT_PORT=30511 DITTO_URL=http://localhost:30525 DITTO_PASSWORD=...
generate-data:
	@bash scripts/demo-oven.sh

## Copy 4 Unity WebGL build files from SRC into ./build/
## Usage: make copy-build SRC=/path/to/source
copy-build:
	@bash scripts/copy-build.sh $(SRC)
