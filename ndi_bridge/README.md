# NDI Bridge Addon

Receives NDI (Network Device Interface) streams from your network and serves them as MJPEG. Used by the **NDI Camera** integration for discovery and streaming.

## Configuration

- **port**: HTTP port for the API and MJPEG stream (default: 8080).
- **source_name**: Optional. NDI source name to stream by default (e.g. `"HOST (SOURCE)"`). Leave empty to select via the integration or POST /source.

## API

- `GET /sources` – JSON list of discovered NDI source names.
- `GET /source` – Current source name.
- `POST /source` – Set current source. Body: `{"source_name": "FULL_NDI_NAME"}`.
- `GET /stream.mjpg` – MJPEG live stream.
- `GET /health` – Health check.

## Requirements

- **Host network**: Must run with host network so NDI multicast discovery works. Enable in the addon configuration.
- NDI sources must be on the same network as the Home Assistant host.
