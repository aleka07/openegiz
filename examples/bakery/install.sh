#!/usr/bin/env bash
# Push the bakery simulator from this repo onto the OpenEgiz host and, unless
# told otherwise, create the twins there.
#
# Run this from a LAPTOP that has ssh access to the host.
#
#   HOST=<ssh-host> bash examples/bakery/install.sh              # rsync + create twins
#   HOST=<ssh-host> bash examples/bakery/install.sh --no-twins   # rsync only
#   HOST=<ssh-host> REMOTE_DIR=course/bakery bash examples/bakery/install.sh
#
# The host needs a venv with paho-mqtt at ~/course/venv
# (bootstrap.sh --with-course-tools creates it).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:?set HOST to the ssh host that runs OpenEgiz, e.g. HOST=my-server}"
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
