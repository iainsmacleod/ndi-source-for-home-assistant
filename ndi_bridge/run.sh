#!/usr/bin/env sh
set -e

# Server reads /data/options.json when run as addon; env overrides for local runs
export NDI_BRIDGE_PORT="${NDI_BRIDGE_PORT:-8080}"
export NDI_BRIDGE_SOURCE_NAME="${NDI_BRIDGE_SOURCE_NAME:-}"

exec python3 /app/server.py
