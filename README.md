# NDI Source for Home Assistant

Show NDI (Network Device Interface) video sources broadcast on your network in Home Assistant dashboards.

## Components

- **Addon (NDI Bridge)**: Receives NDI streams and serves them as MJPEG with an API for source discovery.
- **Integration (NDI Camera)**: Discovers NDI sources and creates camera entities. Both are installed via HACS.

## Installation

### 1. Add the repo in HACS and install the NDI Bridge addon

1. Open **HACS** → **Add-ons** → **+** (Custom repositories)
2. Add this repository URL and choose category **Add-on**, then **Add**:
   ```
   https://github.com/iainsmacleod/ndi-source-for-home-assistant
   ```
3. Find **NDI Bridge** in the list and install it
4. Start the addon and ensure it has host network access (needed for NDI discovery)

### 2. Install the NDI Camera integration (same repo)

1. In HACS go to **Integrations** → **+** (Custom repositories) and add the same repo URL with category **Integration**
2. Search for **NDI Camera** and install it
3. Restart Home Assistant when prompted

### 3. Add the integration and configure

1. **Settings** → **Devices & services** → **Add integration**
2. Search for **NDI Camera**
3. When asked for **Bridge URL**, enter the URL where the NDI Bridge addon is reachable (see below)
4. Pick an NDI source and name your camera
5. Add a **Picture** or **Camera** card to a dashboard and select the NDI camera entity

## Bridge URL (configuration value)

The **Bridge URL** is the address of your NDI Bridge addon’s API and stream.

- **Same machine as Home Assistant**: use **`http://localhost:8080`** (or `http://127.0.0.1:8080`). The addon listens on port 8080 by default.
- **Home Assistant OS / Supervised (addon on host)**: if the integration cannot reach `localhost`, use the IP of your Home Assistant host, e.g. **`http://192.168.1.100:8080`** (replace with your HA host’s IP). You can see this in **Settings** → **System** → **Network**.
- If you changed the addon’s port in its options, use that port instead of 8080.

So in most cases set **Bridge URL** to **`http://localhost:8080`**.

## Requirements

- Home Assistant OS or Supervised installation (for the addon)
- NDI sources on the same network (or reachable by the host)
- For NDI discovery, the addon runs with host network so it can see NDI multicast traffic

## License

This project is not affiliated with NDI or Vizrt. NDI is a trademark of Vizrt Group. Use of the NDI SDK is subject to [NDI’s license terms](https://ndi.video/for-developers/ndi-sdk/).
