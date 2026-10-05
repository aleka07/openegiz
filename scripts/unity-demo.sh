#!/usr/bin/env bash
# Download the demo Unity WebGL scene into ./build/.
# The scene is 88 MB, so it lives in a GitHub release, not in git:
# every clone of the platform (and every contest team repo) stays small.
set -euo pipefail

BASE=${UNITY_DEMO_URL:-https://github.com/aleka07/openegiz/releases/download/unity-demo-1}
cd "$(dirname "$0")/.."

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1
}

# sha256  release asset  file in build/
while read -r sum asset name; do
  dest="build/$name"
  if [ -f "$dest" ] && [ "$(sha256 "$dest")" = "$sum" ]; then
    echo "  ok          $name"
    continue
  fi
  echo "  downloading $name"
  curl -fL --retry 3 -o "$dest.part" "$BASE/$asset"
  if [ "$(sha256 "$dest.part")" != "$sum" ]; then
    rm -f "$dest.part"
    echo "error: checksum mismatch for $asset" >&2
    exit 1
  fi
  mv "$dest.part" "$dest"
done <<'EOF'
04cac932e69a0a7b2cc6a3819f6e891d90325c7739e4dfffc0c4aa6a1ca6e3b6 webgl-build.loader.js WebGL Build.loader.js
120a539241dd505f6d0bdeab0b91d89f9343d3fb5b6e35bdcc807993df9f42ca webgl-build.framework.js WebGL Build.framework.js
64fe8e3ef572e3657f3fe2b7ac757aa30527ce285288b14ffc5b382d953f90fc webgl-build.data WebGL Build.data
827439ecaf5dc303bf9e7c7cdfd324a87eca4114e89fc9a6ae91f627290e8344 webgl-build.wasm WebGL Build.wasm
EOF

echo "Demo scene in build/. Loader URL for the Unity panel: http://localhost:${UNITY_PORT:-8090}/build/WebGL%20Build.loader.js"
