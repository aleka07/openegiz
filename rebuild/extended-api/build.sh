#!/usr/bin/env bash
#
# Rebuild the Eclipse Ditto Extended API image natively on arm64 (gx10-11).
#
# Upstream sources carry NO license -> the image stays LOCAL. Never push it
# to Docker Hub or any other registry.
#
# Run this ON the arm64 host (gx10-11), not on the Mac.
#
set -euo pipefail

REPO_URL="https://github.com/ertis-research/extended-api-for-eclipse-ditto.git"
# Pinned commit, verified 2026-08-07 ("chore: add .env.example file", 2026-05-04)
COMMIT="b49663dea326854a2323423eaeab7e7f54d325a7"
SHORT_SHA="b49663d"

BUILD_ROOT="${BUILD_ROOT:-$HOME/openegiz-build}"
SRC_DIR="$BUILD_ROOT/extended-api"
IMAGE="openegiz/ditto-extended-api"
TARBALL="$BUILD_ROOT/ditto-extended-api-arm64.tar.gz"

# This script lives next to the Dockerfile it needs.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- 1. Fetch sources at the pinned commit ----------------------------------
mkdir -p "$BUILD_ROOT"
if [ -d "$SRC_DIR/.git" ]; then
  git -C "$SRC_DIR" fetch --all --tags
else
  git clone "$REPO_URL" "$SRC_DIR"
fi
git -C "$SRC_DIR" checkout --force "$COMMIT"

test "$(git -C "$SRC_DIR" rev-parse HEAD)" = "$COMMIT" \
  || { echo "FATAL: commit mismatch" >&2; exit 1; }

# --- 2. Dockerfile ----------------------------------------------------------
# Upstream ships Dockerfile.sample. Our version differs in exactly one respect:
# it copies yarn.lock and runs `yarn install --frozen-lockfile`, so the
# dependency tree is pinned instead of re-resolved on every build.
cp "$SCRIPT_DIR/Dockerfile" "$SRC_DIR/Dockerfile"

# --- 3. Build (native arm64, no emulation) ----------------------------------
docker build \
  -t "$IMAGE:arm64-$SHORT_SHA" \
  -t "$IMAGE:latest" \
  "$SRC_DIR"

# --- 4. Smoke test ----------------------------------------------------------
echo "== arch =="
docker image inspect "$IMAGE:latest" --format '{{.Architecture}}/{{.Os}}'
echo "== node =="
docker run --rm --entrypoint node "$IMAGE:latest" --version

echo "== app start =="
docker rm -f eapi-smoke >/dev/null 2>&1 || true
docker run -d --rm --name eapi-smoke -p 18080:8080 "$IMAGE:latest" >/dev/null
sleep 12
docker logs eapi-smoke 2>&1 | head -20
# 404 on / is expected and sufficient: it proves express is bound and serving.
# MongoRuntimeError against the IP_MONGODB placeholder is also expected.
curl -s -o /dev/null -w 'http_code=%{http_code}\n' http://localhost:18080/ || true
docker rm -f eapi-smoke >/dev/null 2>&1 || true

# --- 5. Export for k3s ------------------------------------------------------
docker save "$IMAGE:latest" "$IMAGE:arm64-$SHORT_SHA" | gzip > "$TARBALL"
ls -lh "$TARBALL"

# --- 6. Import into k3s containerd -----------------------------------------
if sudo k3s ctr version >/dev/null 2>&1; then
  gunzip -c "$TARBALL" | sudo k3s ctr images import -
  sudo k3s ctr images ls -q | grep ditto-extended-api
else
  echo "k3s not available; skipping import. Import later with:"
  echo "  gunzip -c $TARBALL | sudo k3s ctr images import -"
fi

# NOTE: workloads must use imagePullPolicy: IfNotPresent (or Never).
# The image exists only in the local containerd store; a pull would 404.
