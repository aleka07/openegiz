#!/usr/bin/env bash
# Push the bakery simulator from this repo onto the OpenEgiz host and, unless
# told otherwise, create the twins there.
#
# Run this from a LAPTOP that has ssh access to the host.
#
#   bash data-generator/bakery/install.sh                 # rsync + create twins
#   bash data-generator/bakery/install.sh --no-twins      # rsync only
#   HOST=vpn-gx10-11 REMOTE_DIR=course/bakery bash install.sh
#
# The host already has a venv with paho-mqtt at ~/course/venv.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-vpn-gx10-11}"
REMOTE_DIR="${REMOTE_DIR:-course/bakery}"
CREATE_TWINS=1
[[ "${1:-}" == "--no-twins" ]] && CREATE_TWINS=0

echo "==> rsync $HERE/ -> $HOST:$REMOTE_DIR/"
ssh -o BatchMode=yes "$HOST" "mkdir -p ~/$REMOTE_DIR"
rsync -az --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$HERE/" "$HOST:$REMOTE_DIR/"
ssh -o BatchMode=yes "$HOST" "chmod +x ~/$REMOTE_DIR/*.sh"

if [[ "$CREATE_TWINS" == "1" ]]; then
  echo "==> creating twins in Ditto"
  ssh -o BatchMode=yes "$HOST" "bash ~/$REMOTE_DIR/create_twins.sh"
fi

cat <<EOF

Installed. Run a shift on the host:

  ssh $HOST
  ~/course/venv/bin/python ~/$REMOTE_DIR/simulator.py --batches 20 --speedup 200

EOF
