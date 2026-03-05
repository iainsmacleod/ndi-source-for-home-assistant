#!/usr/bin/env sh
set -e

# Server reads /data/options.json when run as addon; env overrides for local runs
export NDI_BRIDGE_PORT="${NDI_BRIDGE_PORT:-8080}"
export NDI_BRIDGE_SOURCE_NAME="${NDI_BRIDGE_SOURCE_NAME:-}"

# NDI SDK reads config from NDI_CONFIG_DIR/ndi-config.v1.json (or $HOME/.ndi)
# Use /data/.ndi (writable in addon); server writes config there when discovery_server is set
export HOME="${HOME:-/root}"
export NDI_CONFIG_DIR="${NDI_CONFIG_DIR:-/data/.ndi}"
mkdir -p "$NDI_CONFIG_DIR"

exec python3 /app/server.py
