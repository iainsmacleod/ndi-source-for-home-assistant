#!/usr/bin/env sh
set -e

# Server reads /data/options.json when run as addon; env overrides for local runs
export NDI_BRIDGE_PORT="${NDI_BRIDGE_PORT:-8080}"
export NDI_BRIDGE_SOURCE_NAME="${NDI_BRIDGE_SOURCE_NAME:-}"

# NDI SDK on Linux reads config from $HOME/.ndi/ndi-config.v1.json or NDI_CONFIG_DIR
# Set before Python starts so the SDK sees them when cyndilib loads
export HOME="${HOME:-/root}"
export NDI_CONFIG_DIR="${NDI_CONFIG_DIR:-/root/.ndi}"
mkdir -p "$NDI_CONFIG_DIR"

exec python3 /app/server.py
