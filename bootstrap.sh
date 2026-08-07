#!/usr/bin/env bash
#
# =============================================================================
#  OpenEgiz — bootstrap a CLEAN aarch64 Ubuntu GX10 into a running platform
# =============================================================================
#
#  !! NOT YET EXECUTED ON A CLEAN MACHINE — validated by review and syntax
#  !! only (bash -n, helm template, dry-read against docs/guides/01-03).
#  !! The owner deliberately declined a live test on a fresh host. Treat the
#  !! first real run as a supervised run: read the failure messages, they all
#  !! point at the guide that explains the step.
#
#  Run this ON the arm64 host, from the repo checkout:
#
#      cd ~/openegiz-deploy/chart && bash bootstrap.sh
#
#  Prerequisites you must arrange yourself (see docs/guides/01):
#      - passwordless sudo for your user  (/etc/sudoers.d/90-openegiz-nopasswd)
#      - your user in the `docker` group  (Docker itself already installed)
#      - a filled-in ~/openegiz-deploy/secrets.values.yaml (see step 3)
#
#  Every step is idempotent: re-running the script on a half-installed host
#  skips what is already done and continues.
#
#  Steps:
#      0  preflight   — aarch64, sudo -n, docker access, outbound https
#      1  cluster     — k3s (--write-kubeconfig-mode 644) + Helm
#      2  image       — build ditto-extended-api arm64, import into containerd
#      3  secrets     — refuse to continue without the override file
#      4  deploy      — helm upgrade --install, wait for 14/14 Running
#      5  smoke       — Ditto / extended API / Grafana + endpoint table
#
#  Optional (default OFF):
#      --with-course-tools   pm4py venv + JaamSim   (docs/notes-course-tools.md)
#      --with-bakery         bakery twins in Ditto  (data-generator/bakery/)
#
#  Hermes is NOT installed here — the owner installs it manually. A pointer to
#  integrations/hermes/install.sh is printed at the end.
#
#  Sources: docs/guides/01-03, docs/install-log.md, docs/notes-course-tools.md.
# =============================================================================

set -euo pipefail

# --- configuration -----------------------------------------------------------
CHART_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_NAME="opentwins"          # MUST stay "opentwins" — several values
NAMESPACE="opentwins"             # reference names derived from the release name
SECRETS_FILE="${SECRETS_FILE:-$HOME/openegiz-deploy/secrets.values.yaml}"
KUBECONFIG_PATH="/etc/rancher/k3s/k3s.yaml"
EXPECTED_PODS=14                  # verified on gx10-11, guide 02
IMAGE_TAG="arm64-b49663d"         # pinned in rebuild/extended-api/build.sh
HELM_TIMEOUT="${HELM_TIMEOUT:-15m}"
POD_WAIT_SECONDS="${POD_WAIT_SECONDS:-900}"

WITH_COURSE_TOOLS=0
WITH_BAKERY=0

JAAMSIM_VER="2026-05"
JAAMSIM_URL="https://github.com/jaamsim/jaamsim/releases/download/v${JAAMSIM_VER}/JaamSim${JAAMSIM_VER}.jar"
JAAMSIM_SHA256="be8229bbe0a545e1e4a10338aa66dfd3c9e23d933c6f65bc3baa904d6f8fceb9"

# --- output helpers ----------------------------------------------------------
if [ -t 1 ]; then
  C_BOLD=$'\033[1m'; C_GREEN=$'\033[0;32m'; C_YELLOW=$'\033[1;33m'
  C_RED=$'\033[0;31m'; C_CYAN=$'\033[0;36m'; C_DIM=$'\033[2m'; C_RESET=$'\033[0m'
else
  C_BOLD=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_CYAN=""; C_DIM=""; C_RESET=""
fi

step() { printf '\n%s==> %s%s\n' "$C_BOLD" "$*" "$C_RESET"; }
ok()   { printf '  %s[ ok ]%s %s\n'   "$C_GREEN"  "$C_RESET" "$*"; }
skip() { printf '  %s[skip]%s %s\n'   "$C_DIM"    "$C_RESET" "$*"; }
warn() { printf '  %s[warn]%s %s\n'   "$C_YELLOW" "$C_RESET" "$*"; }
info() { printf '  %s\n' "$*"; }

# die <message> [guide pointer...]
die() {
  printf '\n%sFAILED:%s %s\n' "$C_RED" "$C_RESET" "$1" >&2
  shift
  for line in "$@"; do printf '        %s\n' "$line" >&2; done
  exit 1
}

usage() {
  # Print the header comment block: every line from line 2 until the first
  # non-comment line, with the leading "# " stripped.
  awk 'NR>1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
  exit 0
}

# --- argument parsing --------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --with-course-tools) WITH_COURSE_TOOLS=1 ;;
    --with-bakery)       WITH_BAKERY=1 ;;
    -h|--help)           usage ;;
    *) die "unknown argument: $1" "Run 'bash bootstrap.sh --help' for usage." ;;
  esac
  shift
done

printf '%s\n' "$C_BOLD"
cat <<'BANNER'
  ___                 _____     _
 / _ \ _ __  ___ _ _ | ___/____(_)___
| | | | '_ \/ _ \ '_\|  _|/ _  | |_  /
| |_| | |_)|  __/ | | | |_| (_| | |/ /
 \___/| .__/\___|_| |_|___|\__, |_/___|
      |_|                  |___/
BANNER
printf '%s' "$C_RESET"
info "chart:   $CHART_DIR"
info "release: $RELEASE_NAME (ns $NAMESPACE)"
info "secrets: $SECRETS_FILE"
[ "$WITH_COURSE_TOOLS" = 1 ] && info "optional: course tools (pm4py + JaamSim)"
[ "$WITH_BAKERY" = 1 ]       && info "optional: bakery twins"

# =============================================================================
# STEP 0 — preflight
# =============================================================================
step "Step 0/5 — preflight"

# 0.1 architecture
arch="$(uname -m)"
if [ "$arch" != "aarch64" ]; then
  die "this host is '$arch', not aarch64." \
      "OpenEgiz is built and verified for arm64 only: the ditto-extended-api" \
      "image is rebuilt natively (rebuild/extended-api/) and MongoDB runs on" \
      "the multi-arch mongo:6.0 image." \
      "See docs/guides/02 – Установка платформы на ARM64.md"
fi
ok "architecture: aarch64"

# 0.2 running as root would put k3s/kubeconfig and ~/openegiz-* in /root
if [ "$(id -u)" = "0" ]; then
  die "do not run this as root." \
      "Run as your normal user with passwordless sudo — the script sudo's only" \
      "where it must (k3s install, k3s ctr images import)." \
      "See docs/guides/01 – Подготовка машины, k3s и Helm.md, Шаг 0"
fi
ok "running as unprivileged user: $(id -un)"

# 0.3 passwordless sudo — `sudo -n true` fails loudly instead of hanging on a prompt
if ! sudo -n true 2>/dev/null; then
  die "passwordless sudo is not available for user '$(id -un)'." \
      "Non-interactive sudo is required for the k3s install and for" \
      "'sudo k3s ctr images import'. Grant it with:" \
      "    sudo visudo -f /etc/sudoers.d/90-openegiz-nopasswd" \
      "    $(id -un) ALL=(ALL) NOPASSWD:ALL" \
      "See docs/guides/01 – Подготовка машины, k3s и Helm.md, Шаг 0"
fi
ok "passwordless sudo"

# 0.4 docker: needed once, to build the extended API image (guide 02, step 1)
if ! command -v docker >/dev/null 2>&1; then
  die "docker is not installed." \
      "It is needed exactly once, to build the arm64 ditto-extended-api image." \
      "See docs/guides/02 – Установка платформы на ARM64.md, Шаг 1"
fi
if ! docker info >/dev/null 2>&1; then
  die "docker is installed but user '$(id -un)' cannot talk to the daemon." \
      "Add yourself to the docker group and start a NEW login session:" \
      "    sudo usermod -aG docker $(id -un) && exec newgrp docker" \
      "See docs/guides/01 – Подготовка машины, k3s и Helm.md"
fi
ok "docker reachable: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo 'unknown version')"

# 0.5 outbound https — k3s installer, Helm installer, container images.
# Deliberately no -f: we are testing that the connection and TLS handshake
# work, not that the root path returns 200 (raw.githubusercontent.com/ does
# not). A non-zero curl exit here means genuinely no route out.
for host in get.k3s.io raw.githubusercontent.com; do
  if ! curl -s -o /dev/null --max-time 15 "https://$host"; then
    die "no outbound HTTPS to https://$host" \
        "First install needs the internet: k3s binary from get.k3s.io, Helm from" \
        "raw.githubusercontent.com, plus all container images and the vendored" \
        "Grafana plugins on first pod start." \
        "See docs/guides/01 – Подготовка машины, k3s и Helm.md"
  fi
done
ok "outbound HTTPS to get.k3s.io and raw.githubusercontent.com"

# 0.6 disk — images + PVCs; guide 01 expects "tens of gigabytes"
avail_gb="$(df -BG --output=avail / | tail -1 | tr -dc '0-9')"
if [ -n "$avail_gb" ] && [ "$avail_gb" -lt 20 ]; then
  die "only ${avail_gb}G free on / — need at least 20G." \
      "Container images alone are several GB, plus PVCs for InfluxDB, MongoDB" \
      "and Grafana." \
      "See docs/guides/01 – Подготовка машины, k3s и Helm.md"
fi
ok "disk free on /: ${avail_gb:-unknown}G"

# 0.7 the chart must actually be here
[ -f "$CHART_DIR/Chart.yaml" ] || \
  die "no Chart.yaml in $CHART_DIR — run this script from the repo checkout." \
      "See docs/guides/02 – Установка платформы на ARM64.md, Шаг 2"
ok "chart found: $CHART_DIR/Chart.yaml"

# =============================================================================
# STEP 1 — k3s + Helm
# =============================================================================
step "Step 1/5 — k3s cluster and Helm"

if command -v k3s >/dev/null 2>&1 && sudo -n systemctl is-active --quiet k3s 2>/dev/null; then
  skip "k3s already installed and running: $(k3s --version 2>/dev/null | head -1)"
else
  info "installing k3s (--write-kubeconfig-mode 644) ..."
  # 644 so kubectl works without sudo; without it k3s.yaml is 600 root-owned.
  curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644 \
    || die "the k3s installer failed." \
           "See docs/guides/01 – Подготовка машины, k3s и Helm.md, Шаг 1"
  ok "k3s installed"
fi

# Never rely on ~/.bashrc: it early-exits for non-interactive shells (guide 01,
# "Грабля вторая"). Export explicitly, always.
[ -r "$KUBECONFIG_PATH" ] || \
  die "$KUBECONFIG_PATH is missing or unreadable." \
      "k3s should have written it with mode 644. Check: sudo systemctl status k3s" \
      "See docs/guides/01 – Подготовка машины, k3s и Helm.md, Шаг 1"
export KUBECONFIG="$KUBECONFIG_PATH"
ok "KUBECONFIG=$KUBECONFIG"

info "waiting for the node to become Ready (up to 5 min) ..."
if ! kubectl wait --for=condition=Ready node --all --timeout=300s >/dev/null 2>&1; then
  kubectl get nodes -o wide || true
  die "the node did not reach Ready within 5 minutes." \
      "Diagnose with: sudo journalctl -u k3s -n 100 --no-pager" \
      "See docs/guides/01 – Подготовка машины, k3s и Helm.md, Шаг 2"
fi
ok "node Ready: $(kubectl get nodes --no-headers | awk '{print $1}' | tr '\n' ' ')"

# kube-system converges after the node is Ready (54 s on gx10-11). We do not
# gate on it: helm install would wait for the same images anyway, and
# helm-install-traefik legitimately restarts twice before Completed.
info "kube-system pods:"
kubectl get pods -n kube-system --no-headers 2>/dev/null | sed 's/^/    /' || true

if command -v helm >/dev/null 2>&1; then
  skip "Helm already installed: $(helm version --short)"
else
  info "installing Helm 3 ..."
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash \
    || die "the Helm installer failed." \
           "See docs/guides/01 – Подготовка машины, k3s и Helm.md, Шаг 3"
  ok "Helm installed: $(helm version --short)"
fi

# Convenience only — every command in this script exports KUBECONFIG itself.
if ! grep -q "KUBECONFIG=$KUBECONFIG_PATH" "$HOME/.bashrc" 2>/dev/null; then
  printf '\nexport KUBECONFIG=%s\n' "$KUBECONFIG_PATH" >> "$HOME/.bashrc"
  ok "added KUBECONFIG export to ~/.bashrc"
else
  skip "~/.bashrc already exports KUBECONFIG"
fi

# =============================================================================
# STEP 2 — ditto-extended-api arm64 image
# =============================================================================
step "Step 2/5 — build and import ditto-extended-api ($IMAGE_TAG)"

# The upstream image ertis/ditto-extended-api is amd64-only, so this image
# exists ONLY in the local containerd store. values.yaml pins the tag with
# pullPolicy IfNotPresent; a missing image means ImagePullBackOff.
#
# NOTE: it must be `sudo k3s ctr`, never a bare `ctr` — on a host with Docker
# installed, k3s skips its own /usr/local/bin/ctr symlink and the Docker `ctr`
# talks to the WRONG containerd (guide 01, "Грабля первая"). build.sh already
# does the right thing; this check mirrors it.
if sudo -n k3s ctr images ls -q 2>/dev/null | grep -q "ditto-extended-api:$IMAGE_TAG"; then
  skip "image already in k3s containerd: openegiz/ditto-extended-api:$IMAGE_TAG"
else
  info "building natively on arm64 (clone + docker build + smoke test + import) ..."
  info "expect a few minutes and a ~142 MB tarball in ~/openegiz-build/"
  bash "$CHART_DIR/rebuild/extended-api/build.sh" \
    || die "rebuild/extended-api/build.sh failed." \
           "Read its output above: it clones a PINNED upstream commit, builds," \
           "smoke-tests, exports and imports into k3s containerd." \
           "A MongoRuntimeError against IP_MONGODB and HTTP 404 on / during the" \
           "smoke test are EXPECTED and not failures." \
           "See docs/guides/02 – Установка платформы на ARM64.md, Шаг 1" \
           "and docs/notes-extended-api-build.md"

  sudo -n k3s ctr images ls -q 2>/dev/null | grep -q "ditto-extended-api:$IMAGE_TAG" \
    || die "build.sh finished but the image is not in k3s containerd." \
           "Check with: sudo k3s ctr images ls -q | grep extended-api" \
           "Import manually:" \
           "  gunzip -c ~/openegiz-build/ditto-extended-api-arm64.tar.gz | sudo k3s ctr images import -" \
           "See docs/guides/02 – Установка платформы на ARM64.md, Шаг 1"
  ok "image built and imported: openegiz/ditto-extended-api:$IMAGE_TAG"
fi

# =============================================================================
# STEP 3 — secrets override
# =============================================================================
step "Step 3/5 — secrets override"

if [ ! -f "$SECRETS_FILE" ]; then
  die "secrets override not found: $SECRETS_FILE" \
      "" \
      "values.yaml ships deliberately INVALID placeholders for every credential," \
      "so installing without this file would break Ditto auth and telemetry" \
      "ingest. Create it now:" \
      "" \
      "    mkdir -p \"$(dirname "$SECRETS_FILE")\"" \
      "    cp \"$CHART_DIR/secrets.values.yaml.example\" \"$SECRETS_FILE\"" \
      "    chmod 600 \"$SECRETS_FILE\"" \
      "    \$EDITOR \"$SECRETS_FILE\"      # replace every CHANGE_ME" \
      "" \
      "Generate each secret with:  openssl rand -base64 18" \
      "Then re-run this script. Never commit the filled-in file."
fi

# Reject a file that was copied but not filled in — otherwise the install
# "succeeds" with the literal password CHANGE_ME.
if grep -q 'CHANGE_ME' "$SECRETS_FILE"; then
  die "$SECRETS_FILE still contains CHANGE_ME placeholders." \
      "Replace every one of them (openssl rand -base64 18), then re-run." \
      "Leave the two 'user:' values as ditto / devops — the post-install" \
      "connections hardcode the subject nginx:ditto."
fi

python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1]))' "$SECRETS_FILE" \
  || die "$SECRETS_FILE is not valid YAML." \
         "Compare it against $CHART_DIR/secrets.values.yaml.example"

perms="$(stat -c '%a' "$SECRETS_FILE" 2>/dev/null || echo '')"
if [ "$perms" != "600" ]; then
  chmod 600 "$SECRETS_FILE"
  warn "tightened $SECRETS_FILE from ${perms:-unknown} to 600"
fi
ok "secrets override present, filled in, valid YAML, mode 600"

# =============================================================================
# STEP 4 — helm install / upgrade
# =============================================================================
step "Step 4/5 — deploy the chart"

# The Grafana app plugin is a FRONTEND plugin: it calls Ditto and the extended
# API from the USER'S BROWSER, so those URLs must be the host's LAN IP, not a
# cluster-internal DNS name. values.yaml hardcodes gx10-11's 192.168.0.135,
# which is wrong on any other machine — so we override it from the node's
# actual InternalIP.
NODE_IP="$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || true)"
[ -n "$NODE_IP" ] || die "could not read the node InternalIP." \
                         "Check: kubectl get nodes -o wide"
ok "node IP for the Grafana plugin URLs: $NODE_IP"

# Subcharts are vendored in charts/, so `helm dependency build` is NOT needed
# and no external repo is contacted (guide 02, step 2).
info "rendering the chart as a dry check ..."
helm template "$RELEASE_NAME" "$CHART_DIR" -n "$NAMESPACE" \
  -f "$SECRETS_FILE" >/dev/null \
  || die "the chart does not render — refusing to install." \
         "See docs/guides/02 – Установка платформы на ARM64.md, Шаг 2"
ok "chart renders cleanly"

# upgrade --install is the idempotent form of `make install` / `make upgrade`.
# Release name is nailed to "opentwins": several values reference names derived
# from it (e.g. the configmap opentwins-telegraf-real-config).
info "helm upgrade --install (timeout $HELM_TIMEOUT) ..."
if ! helm upgrade --install "$RELEASE_NAME" "$CHART_DIR" \
      -n "$NAMESPACE" --create-namespace \
      -f "$SECRETS_FILE" \
      --set "grafanaPlugin.dittoURL=http://$NODE_IP:30525" \
      --set "grafanaPlugin.extendedURL=http://$NODE_IP:30528" \
      --wait --timeout="$HELM_TIMEOUT"; then
  printf '\n%s--- diagnostics ---%s\n' "$C_YELLOW" "$C_RESET" >&2
  kubectl get pods -n "$NAMESPACE" -o wide >&2 || true
  kubectl get events -n "$NAMESPACE" --sort-by=.lastTimestamp 2>/dev/null | tail -30 >&2 || true
  for p in $(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
             | awk '$3 != "Running" && $3 != "Completed" {print $1}'); do
    printf '\n%s--- describe %s ---%s\n' "$C_YELLOW" "$p" "$C_RESET" >&2
    kubectl describe pod -n "$NAMESPACE" "$p" 2>/dev/null | tail -25 >&2 || true
    printf '%s--- logs %s (last 30) ---%s\n' "$C_YELLOW" "$p" "$C_RESET" >&2
    kubectl logs -n "$NAMESPACE" "$p" --tail=30 --all-containers 2>/dev/null >&2 || true
  done
  die "helm upgrade --install did not converge." \
      "Two failure modes account for almost everything:" \
      "  * extended-api in ImagePullBackOff -> the local image is missing or" \
      "    pullPolicy is not IfNotPresent (guide 02, правка 1)" \
      "  * the five Ditto JVM services OOMKilled with exit code 137 -> the" \
      "    -XX:MaxRAM override in values.yaml was lost (guide 02, правка 3)" \
      "Start over cleanly: helm uninstall $RELEASE_NAME -n $NAMESPACE," \
      "then delete PVCs, jobs and pods as described in guide 02, «Если надо" \
      "начать с нуля» — InfluxDB will not re-bootstrap on an initialised PVC." \
      "See docs/guides/02 – Установка платформы на ARM64.md"
fi
ok "helm release deployed"

info "waiting for $EXPECTED_PODS pods to be Running (up to $((POD_WAIT_SECONDS/60)) min) ..."
deadline=$(( $(date +%s) + POD_WAIT_SECONDS ))
running=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  running="$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
             | awk '$3 == "Running" {c++} END {print c+0}')"
  [ "$running" -ge "$EXPECTED_PODS" ] && break
  sleep 5
done

if [ "$running" -lt "$EXPECTED_PODS" ]; then
  printf '\n%s--- diagnostics ---%s\n' "$C_YELLOW" "$C_RESET" >&2
  kubectl get pods -n "$NAMESPACE" -o wide >&2 || true
  kubectl get events -n "$NAMESPACE" --sort-by=.lastTimestamp 2>/dev/null | tail -30 >&2 || true
  die "only $running/$EXPECTED_PODS pods Running after $((POD_WAIT_SECONDS/60)) minutes." \
      "On gx10-11 (20 CPU / 121 GB) this takes 57 seconds; a slower host or a" \
      "cold image pull can legitimately take longer — re-run the script, it is" \
      "idempotent. If pods are stuck, see the two failure modes above." \
      "See docs/guides/02 – Установка платформы на ARM64.md, Шаг 3"
fi
ok "$running/$EXPECTED_PODS pods Running"

# =============================================================================
# STEP 5 — post-install smoke test
# =============================================================================
step "Step 5/5 — smoke test"

# Read the passwords straight out of the override file so they never land in
# the shell history or in `ps` output. The python must succeed — an empty
# result would leave the variables unset and `set -u` would abort with a
# confusing message instead of a useful one.
creds="$(python3 - "$SECRETS_FILE" <<'PYEOF'
import sys, yaml, shlex
v = yaml.safe_load(open(sys.argv[1]))
b = v["ditto"]["global"]["basicAuthUsers"]
print("DITTO_USER=%s"   % shlex.quote(b["ditto"]["user"]))
print("DITTO_PW=%s"     % shlex.quote(b["ditto"]["password"]))
print("DEVOPS_USER=%s"  % shlex.quote(b["devops"]["user"]))
print("DEVOPS_PW=%s"    % shlex.quote(b["devops"]["password"]))
print("GRAFANA_PW=%s"   % shlex.quote(v["grafana"]["adminPassword"]))
PYEOF
)" || die "could not read credentials out of $SECRETS_FILE." \
          "Its key structure must match $CHART_DIR/secrets.values.yaml.example" \
          "See docs/guides/03 – Проверка и сквозной тест.md"
eval "$creds"
unset creds

smoke_fail=0

# Ditto REST API through nginx. On a fresh install "[]" is the correct answer.
code="$(curl -s -o /tmp/openegiz-smoke.out -w '%{http_code}' --max-time 20 \
        -u "$DITTO_USER:$DITTO_PW" "http://localhost:30525/api/2/things" || echo 000)"
if [ "$code" = "200" ]; then
  ok "Ditto API :30525/api/2/things -> 200 ($(head -c 40 /tmp/openegiz-smoke.out))"
else
  warn "Ditto API :30525/api/2/things -> $code (expected 200)"
  smoke_fail=1
fi

# Ditto health through the devops user.
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        -u "$DEVOPS_USER:$DEVOPS_PW" "http://localhost:30525/status/health" || echo 000)"
if [ "$code" = "200" ]; then
  ok "Ditto health :30525/status/health -> 200"
else
  warn "Ditto health :30525/status/health -> $code (expected 200)"
  smoke_fail=1
fi

# Extended API. NOTE: `/` returns 404 by design (no such route) — that is what
# guides 02/03 check. The real liveness signal is /api/twins/, which returns
# 200 with an empty list on a fresh install. Verified on gx10-11 2026-08-07.
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        "http://localhost:30528/api/twins/" || echo 000)"
if [ "$code" = "200" ]; then
  ok "Extended API :30528/api/twins/ -> 200"
else
  warn "Extended API :30528/api/twins/ -> $code (expected 200; / returning 404 is normal, /api/twins/ is not)"
  smoke_fail=1
fi

# Grafana login page.
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        "http://localhost:30718/login" || echo 000)"
if [ "$code" = "200" ]; then
  ok "Grafana :30718/login -> 200"
else
  warn "Grafana :30718/login -> $code (expected 200)"
  smoke_fail=1
fi

# Grafana datasource: proves the sidecar provisioned "opentwins" AND that the
# admin password from the override file actually took effect.
if curl -s --max-time 20 -u "admin:$GRAFANA_PW" \
     "http://localhost:30718/api/datasources" 2>/dev/null | grep -q 'opentwins'; then
  ok "Grafana datasource 'opentwins' provisioned (admin password works)"
else
  warn "Grafana datasource 'opentwins' not found, or the admin password was rejected"
  warn "  note: Grafana keeps the admin password in its own DB after first start —"
  warn "  on a REUSED PVC grafana.adminPassword is ignored (guide 04)"
  smoke_fail=1
fi

# InfluxDB health (no auth needed).
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        "http://localhost:30716/health" || echo 000)"
if [ "$code" = "200" ]; then
  ok "InfluxDB :30716/health -> 200"
else
  warn "InfluxDB :30716/health -> $code (expected 200)"
  smoke_fail=1
fi

rm -f /tmp/openegiz-smoke.out
unset DITTO_PW DEVOPS_PW GRAFANA_PW

if [ "$smoke_fail" != 0 ]; then
  warn "some smoke checks failed — the platform is up but not fully healthy."
  warn "Per-service diagnosis: docs/guides/03 – Проверка и сквозной тест.md"
fi

# =============================================================================
# OPTIONAL — course tools (pm4py + JaamSim)
# =============================================================================
if [ "$WITH_COURSE_TOOLS" = 1 ]; then
  step "Optional — course tools (pm4py venv + JaamSim)"
  # Everything here lives OUTSIDE the cluster. Source: docs/notes-course-tools.md
  COURSE_DIR="$HOME/course"
  mkdir -p "$COURSE_DIR"

  if [ -x "$COURSE_DIR/venv/bin/python" ]; then
    skip "venv already exists: $COURSE_DIR/venv"
  else
    info "installing python3-venv, python3-pip, graphviz (dot renders process maps) ..."
    sudo -n apt-get update -qq \
      && sudo -n apt-get install -y -qq python3-venv python3-pip graphviz \
      || die "apt-get failed while installing python3-venv / graphviz." \
             "See docs/notes-course-tools.md"
    python3 -m venv "$COURSE_DIR/venv" \
      || die "python3 -m venv failed." "See docs/notes-course-tools.md"
    ok "venv created: $COURSE_DIR/venv"
  fi

  "$COURSE_DIR/venv/bin/pip" install --quiet --upgrade pip setuptools wheel \
    || die "pip self-upgrade failed." "See docs/notes-course-tools.md"

  # requirements.txt lives on the host in ~/course; fall back to the repo's
  # data-generator requirements, which cover the MQTT/Influx client side.
  req=""
  for cand in "$COURSE_DIR/requirements.txt" "$CHART_DIR/data-generator/requirements.txt"; do
    [ -f "$cand" ] && { req="$cand"; break; }
  done
  if [ -n "$req" ]; then
    info "pip install -r $req ..."
    "$COURSE_DIR/venv/bin/pip" install --quiet -r "$req" \
      || die "pip install -r $req failed." "See docs/notes-course-tools.md"
    ok "python deps installed from $req"
  else
    warn "no requirements.txt found — installing the course minimum by hand"
    "$COURSE_DIR/venv/bin/pip" install --quiet \
      pm4py pandas numpy scipy matplotlib jupyterlab paho-mqtt influxdb-client graphviz \
      || die "pip install of the course minimum failed." "See docs/notes-course-tools.md"
    ok "python deps installed (pm4py, pandas, paho-mqtt, influxdb-client, ...)"
  fi

  # JaamSim: the jar targets Java 8 bytecode, so the stock OpenJDK 8 on the
  # host is enough — nothing is installed and update-alternatives is untouched.
  mkdir -p "$COURSE_DIR/jaamsim"
  jar="$COURSE_DIR/jaamsim/JaamSim${JAAMSIM_VER}.jar"
  if [ -f "$jar" ] && echo "$JAAMSIM_SHA256  $jar" | sha256sum -c --status 2>/dev/null; then
    skip "JaamSim ${JAAMSIM_VER} already present and checksum matches"
  else
    info "downloading JaamSim ${JAAMSIM_VER} (~19 MB) ..."
    curl -sSL --max-time 300 -o "$jar" "$JAAMSIM_URL" \
      || die "JaamSim download failed: $JAAMSIM_URL" "See docs/notes-course-tools.md"
    echo "$JAAMSIM_SHA256  $jar" | sha256sum -c --status \
      || die "JaamSim sha256 mismatch — refusing to keep the file." \
             "Expected $JAAMSIM_SHA256" "See docs/notes-course-tools.md"
    ok "JaamSim ${JAAMSIM_VER} downloaded, sha256 verified"
  fi

  if command -v java >/dev/null 2>&1; then
    ok "java present: $(java -version 2>&1 | head -1)"
    info "headless batch runs use -headless (NOT -b, NOT -batch — both fail with exit 0)"
  else
    warn "no java on PATH — JaamSim needs a JRE. sudo apt-get install -y openjdk-8-jre-headless"
  fi
fi

# =============================================================================
# OPTIONAL — bakery twins
# =============================================================================
if [ "$WITH_BAKERY" = 1 ]; then
  step "Optional — bakery twins"
  twins_script="$CHART_DIR/data-generator/bakery/create_twins.sh"
  if [ ! -f "$twins_script" ]; then
    warn "not found: $twins_script — skipping"
  else
    # create_twins.sh reads the Ditto password from SECRETS_FILE itself.
    # PUT is idempotent for the document but resets feature values to 0 —
    # that is deliberate, it is the "reset the line" button.
    SECRETS_FILE="$SECRETS_FILE" bash "$twins_script" \
      || die "create_twins.sh failed." \
             "It needs a reachable Ditto on \$DITTO_URL (default http://localhost:30525)." \
             "See data-generator/bakery/README.md"
    ok "bakery twins created/updated in Ditto"
    info ""
    info "Run a shift (the simulator needs the course venv, not the system python3):"
    info "    ~/course/venv/bin/python $CHART_DIR/data-generator/bakery/simulator.py --batches 20 --speedup 200"
    info "Full scenario: docs/runbook-bakery-scenario.md"
  fi
fi

# =============================================================================
# DONE — endpoint table
# =============================================================================
step "Done"

printf '\n%sEndpoints (host %s)%s\n' "$C_BOLD" "$NODE_IP" "$C_RESET"
printf '%s%-26s %-8s %s%s\n' "$C_DIM" "SERVICE" "PORT" "URL / NOTE" "$C_RESET"
printf '  %-26s %-8s %s%s%s\n' "Grafana (main UI)"   "30718" "$C_CYAN" "http://$NODE_IP:30718"  "$C_RESET"
printf '  %-26s %-8s %s%s%s\n' "Ditto API (nginx)"   "30525" "$C_CYAN" "http://$NODE_IP:30525"  "$C_RESET"
printf '  %-26s %-8s %s%s%s\n' "Ditto Extended API"  "30528" "$C_CYAN" "http://$NODE_IP:30528"  "$C_RESET"
printf '  %-26s %-8s %s%s%s\n' "InfluxDB 2"          "30716" "$C_CYAN" "http://$NODE_IP:30716"  "$C_RESET"
printf '  %-26s %-8s %s%s%s\n' "Unity WebGL server"  "30530" "$C_CYAN" "http://$NODE_IP:30530"  "$C_RESET"
printf '  %-26s %-8s %s\n'     "Mosquitto MQTT"      "30511" "tcp (+31039 websocket), no auth"
printf '  %-26s %-8s %s\n'     "MongoDB"             "-"     "ClusterIP only, not exposed"
printf '\n  %sLive view any time:%s make endpoints\n' "$C_DIM" "$C_RESET"

cat <<EOF

$C_BOLD Credentials $C_RESET
  Grafana   admin  / (grafana.adminPassword)
  Ditto     $DITTO_USER  / (ditto.global.basicAuthUsers.ditto.password)
  Ditto     $DEVOPS_USER / (…basicAuthUsers.devops.password)
  InfluxDB  admin  / (influxdb2.adminUser.password), org opentwins, bucket default
  All of them live in $SECRETS_FILE (chmod 600). Keep a human-readable copy on
  this host only, e.g. ~/course/CREDENTIALS.md (chmod 600).

$C_BOLD Next steps $C_RESET
  * End-to-end telemetry test  -> docs/guides/03 – Проверка и сквозной тест.md
  * Grafana plugins            -> docs/guides/04 – Grafana-плагины.md
  * Day-to-day operation       -> docs/guides/07 – Эксплуатация.md
  * Bakery scenario            -> docs/runbook-bakery-scenario.md

$C_BOLD Hermes (NOT installed by this script) $C_RESET
  The agent integration is installed manually by the owner:
      bash $CHART_DIR/integrations/hermes/install.sh
  Read integrations/hermes/README.md first — it rewrites ~/.hermes/config.yaml.

$C_YELLOW Reminder:$C_RESET this stand is LAN-only. Mosquitto and the extended API have no
authentication; do not expose this host to the internet.
EOF

exit 0
