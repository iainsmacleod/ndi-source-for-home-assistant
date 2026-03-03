# NDI Source for Home Assistant

Show NDI (Network Device Interface) video sources broadcast on your network in Home Assistant dashboards.

## Components

- **Addon (NDI Bridge)**: Receives NDI streams and serves them as MJPEG with an API for source discovery. Install via the addon repository.
- **Integration (NDI Camera)**: Discovers NDI sources and creates camera entities. Install via HACS.

## Installation

### 1. Add the addon repository

1. In Home Assistant: **Settings** → **Add-ons** → **Add-on store**
2. Click the three dots (⋮) → **Repositories**
3. Add this repository URL and click **Add**:
   ```
   https://github.com/iainsmacleod/ndi-source-for-home-assistant
   ```
4. Install the **NDI Bridge** addon, start it, and ensure it has **host** or appropriate network access for NDI multicast.

### 2. Install the integration via HACS

1. Open **HACS** → **Integrations**
2. Click **+** (Explore & Download Repositories)
3. Search for **NDI Source** or add this repo as a custom repository (category: **Integration**)
4. Install **NDI Camera**
5. Restart Home Assistant

### 3. Configure

1. **Settings** → **Devices & services** → **Add integration**
2. Search for **NDI Camera**
3. Follow the config flow: the integration will use the addon to discover NDI sources; pick one and name your camera
4. Add a **Picture** or **Camera** card to a dashboard and select the NDI camera entity

## Requirements

- Home Assistant OS or Supervised installation (for the addon)
- NDI sources on the same network (or reachable by the host)
- For NDI discovery, the addon runs with host network so it can see NDI multicast traffic

## License

This project is not affiliated with NDI or Vizrt. NDI is a trademark of Vizrt Group. Use of the NDI SDK is subject to [NDI’s license terms](https://ndi.video/for-developers/ndi-sdk/).
