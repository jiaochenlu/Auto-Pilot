#!/usr/bin/env bash
# Start the AgentLoop Task Console on macOS / Linux.
# Usage: ./start-ui.sh [port]   (default port: 8765)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
PORT="${1:-8765}"
PYTHON="${PYTHON:-python3}"
mkdir -p .agentloop
exec "$PYTHON" -m agentloop ui --host 127.0.0.1 --port "$PORT" \
    > ".agentloop/ui-${PORT}.stdout.log" \
    2> ".agentloop/ui-${PORT}.stderr.log"
