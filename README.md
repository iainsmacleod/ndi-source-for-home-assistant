# NDI Source for Home Assistant

Show NDI (Network Device Interface) video sources broadcast on your network in Home Assistant dashboards.

## Components

- **Addon (NDI Bridge)**: Receives NDI streams and serves them as MJPEG with an API for source discovery. Installed from the **Add-on store**.
- **Integration (NDI Camera)**: Discovers NDI sources and creates camera entities. Installed via **HACS**.

HACS does not install add-ons; add-ons are installed from the Add-on store.

## Installation

### 1. Install the NDI Bridge addon (Add-on store)

1. Go to **Settings** → **Add-ons** → **Add-on store**
2. Click the **three dots (⋮)** in the top right → **Repositories**
3. Paste this URL and click **Add**, then **Close**:
   ```
   https://github.com/iainsmacleod/ndi-source-for-home-assistant
   ```
4. Back in the Add-on store, **scroll down**. Custom repos often appear as their own section (e.g. **"NDI Source for Home Assistant"** or the maintainer name). Click that section to see **NDI Bridge**, then install it.
5. If you don’t see it: try the **Refresh** button (if any) in the Add-on store, or restart Home Assistant and open the Add-on store again.
6. Start the addon and turn **Host network** on (needed for NDI discovery)

### 2. Install the NDI Camera integration (HACS)

1. Open **HACS** → **Integrations** → three dots (⋮) → **Custom repositories**
2. Add this repository URL and choose category **Integration**, then **Add**:
   ```
   https://github.com/iainsmacleod/ndi-source-for-home-assistant
   ```
3. Search for **NDI Camera** and install it
4. Restart Home Assistant when prompted

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

## NDI receiver behaviour (vs OBS / DistroAV)

The NDI Bridge uses [cyndilib](https://cyndilib.readthedocs.io/) (Python NDI bindings). The receiver is configured similarly to **[DistroAV](https://github.com/DistroAV/DistroAV)** (OBS NDI plugin): **highest bandwidth**, **`UYVY_BGRA`** colour mode, **`allow_video_fields=True`**, and a stable **`recv_name`** (`HA-NDI-Bridge`). That matches how `ndi-source.cpp` builds `NDIlib_recv_create_v3_t` for normal-latency sources.

Video is then converted to JPEG using the frame **FourCC** / buffer size: **BGRA/BGRX** (4 bytes/pixel) or **UYVY** (2 bytes/pixel). Many webcams and low-latency paths deliver **UYVY**; treating that buffer as BGRA produces garbage or no usable image—this was a common cause of “receiver connected but no snapshot” before UYVY handling was added.

If you still see no video after that, the usual cause is **network/firewall** between the NDI sender and the HA host (discovery can work while the media path is blocked).

## Requirements

- Home Assistant OS or Supervised installation (for the addon)
- NDI sources on the same network (or reachable by the host)
- For NDI discovery, the addon runs with host network so it can see NDI multicast traffic

## License

This project is not affiliated with NDI or Vizrt. NDI is a trademark of Vizrt Group. Use of the NDI SDK is subject to [NDI’s license terms](https://ndi.video/for-developers/ndi-sdk/).
