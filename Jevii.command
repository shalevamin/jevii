#!/bin/bash
# Double-click launcher for jevii (opens Terminal + browser)
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./env.sh
export PATH="$HOME/.local/bin:$PATH"
echo "Starting jevii…"
exec jevii serve --host 127.0.0.1 --port 8765
