"""
NDI Bridge: discovers NDI sources and streams selected one as MJPEG.
API: GET /sources, GET /scan, POST /source, GET /source, GET /stream.mjpg,
     GET /snapshot.jpg, GET /health
"""
import asyncio
import io
import json
import os
import subprocess
import threading
import time
from typing import Optional

from aiohttp import web

OPTIONS_PATH = "/data/options.json"


def load_options() -> dict:
    out = {"port": 8080, "source_name": "", "discovery_server": ""}
    out["port"] = int(os.environ.get("NDI_BRIDGE_PORT", "8080"))
    out["source_name"] = os.environ.get("NDI_BRIDGE_SOURCE_NAME", "")
    out["discovery_server"] = os.environ.get("NDI_BRIDGE_DISCOVERY_SERVER", "")
    if os.path.isfile(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH) as f:
                data = json.load(f)
                out["port"] = int(data.get("port", out["port"]))
                out["source_name"] = data.get("source_name", out["source_name"])
                out["discovery_server"] = data.get("discovery_server", out["discovery_server"])
        except Exception:
            pass
    return out


def _configure_ndi_discovery_server(server_ip: str):
    """Write NDI SDK config file to use a Discovery Server instead of mDNS.

    NDI docs: config at $HOME/.ndi/ndi-config.v1.json (Linux). The "networks"
    object must have "ips" and "discovery" (comma-delimited list of Discovery
    Server IPs). See docs.ndi.video Configuration Files and Discovery Server.
    """
    if not server_ip:
        return
    # Strip whitespace; support comma-delimited list per NDI 5+
    discovery_ips = ",".join(s.strip() for s in server_ip.split(",") if s.strip())
    if not discovery_ips:
        return
    # Minimal config per official docs: ndi.networks.discovery + ndi.networks.ips
    config = {
        "ndi": {
            "networks": {
                "ips": "",
                "discovery": discovery_ips,
            }
        }
    }
    # Addon root FS is read-only; use /data (writable) so the file is actually created
    config_dir = "/data/.ndi"
    try:
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "ndi-config.v1.json")
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
    except OSError as e:
        _log(f"Failed to write NDI config to {config_dir}: {e}")
        return
    if not os.path.isfile(config_path):
        _log(f"Config file missing after write: {config_path}")
        return
    os.environ["HOME"] = "/root"
    os.environ["NDI_CONFIG_DIR"] = config_dir  # SDK loads ndi-config.v1.json from this dir
    _log(f"NDI Discovery Server configured: {discovery_ips} → {config_path} (file ok)")


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
current_source_name: Optional[str] = None
current_source_lock = threading.Lock()

latest_jpeg: Optional[bytes] = None
latest_jpeg_lock = threading.Lock()

mjpeg_subscribers: list = []

_finder = None
_finder_lock = threading.Lock()

_discovery_log: list = []   # circular log of discovery events
_MAX_LOG = 50


def _log(msg: str):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    _discovery_log.append(line)
    if len(_discovery_log) > _MAX_LOG:
        _discovery_log.pop(0)


# ---------------------------------------------------------------------------
# Avahi helper — start or verify avahi-daemon is running
# ---------------------------------------------------------------------------

def _ensure_avahi():
    """Try to start avahi-daemon if it's not running (best-effort)."""
    try:
        result = subprocess.run(
            ["avahi-daemon", "--check"],
            capture_output=True, timeout=3
        )
        if result.returncode == 0:
            _log("avahi-daemon: already running")
            return
    except FileNotFoundError:
        _log("WARNING: avahi-daemon not installed — NDI discovery may not work")
        return
    except Exception as e:
        _log(f"avahi check error: {e}")

    try:
        _log("Starting avahi-daemon...")
        subprocess.Popen(
            ["avahi-daemon", "--no-drop-root", "--daemonize"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(2)
        _log("avahi-daemon started")
    except Exception as e:
        _log(f"Could not start avahi-daemon: {e}")


# ---------------------------------------------------------------------------
# Finder management
# ---------------------------------------------------------------------------

def _make_finder():
    """Create, open, and return a new Finder. Caller holds _finder_lock. No long sleep here so /sources never blocks."""
    try:
        from cyndilib.finder import Finder
        f = Finder()
        f.open()
        _log("Finder opened — discovery in progress (no blocking wait).")
        return f
    except Exception as e:
        _log(f"Finder init error: {e}")
        return None


def _log_initial_discovery():
    """Run in background: wait 3s then log current source count (avoids blocking API)."""
    time.sleep(3)
    with _finder_lock:
        finder = _finder
    if finder:
        names = list(finder.get_source_names())
        _log(f"Initial discovery complete: {names if names else 'no sources found'}")


def _get_finder():
    """Return the global Finder, creating it if needed."""
    global _finder
    with _finder_lock:
        if _finder is None:
            _finder = _make_finder()
        return _finder


def _reset_finder():
    """Destroy and recreate the Finder (for forced rescan)."""
    global _finder
    with _finder_lock:
        if _finder is not None:
            try:
                _finder.close()
            except Exception:
                pass
            _finder = None
        _log("Finder reset — starting fresh discovery...")
        _finder = _make_finder()
        return list(_finder.get_source_names()) if _finder else []


def get_sources_sync() -> list[str]:
    """Return currently known NDI source names."""
    try:
        finder = _get_finder()
        if finder is None:
            return []
        names = list(finder.get_source_names())
        _log(f"get_sources called — found: {names if names else '[]'}")
        return names
    except Exception as e:
        _log(f"Discovery error: {e}")
        return []


def scan_sources_sync() -> list[str]:
    """Force a fresh Finder cycle and return discovered sources."""
    _log("Forced rescan requested")
    return _reset_finder()


# ---------------------------------------------------------------------------
# NDI video → JPEG (aligned with DistroAV / OBS NDI source defaults)
# See: https://github.com/DistroAV/DistroAV — recv_create_v3 uses
# bandwidth=highest, color_format=UYVY_BGRA (normal latency), allow_video_fields=true.
# Many webcams deliver UYVY; assuming BGRA breaks decoding / yields no usable frame.
# ---------------------------------------------------------------------------

def _uyvy_to_rgb_bytes(data: bytes, w: int, h: int) -> bytes:
    """Packed UYVY (4:2:2) → RGB888, same layout as NDI uses for UYVY."""
    out = bytearray(w * h * 3)
    o = 0
    idx = 0
    exp = w * h * 2
    if len(data) < exp:
        return b""
    for _y in range(h):
        for _x in range(0, w, 2):
            u = data[idx] - 128
            y0 = data[idx + 1]
            v = data[idx + 2] - 128
            y1 = data[idx + 3]
            idx += 4

            def yuv_to_rgb(y: int, u: int, v: int) -> tuple[int, int, int]:
                r = int(y + 1.402 * v)
                g = int(y - 0.344 * u - 0.714 * v)
                b = int(y + 1.772 * u)
                return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))

            r0, g0, b0 = yuv_to_rgb(y0, u, v)
            r1, g1, b1 = yuv_to_rgb(y1, u, v)
            out[o] = r0
            out[o + 1] = g0
            out[o + 2] = b0
            o += 3
            if _x + 1 < w:
                out[o] = r1
                out[o + 1] = g1
                out[o + 2] = b1
                o += 3
    return bytes(out)


def _video_frame_to_jpeg(vf, raw: bytes, quality: int = 85) -> Optional[bytes]:
    """Convert NDI video buffer to JPEG; handles BGRA/BGRX and UYVY."""
    from PIL import Image

    w, h = vf.get_resolution()
    buf_size = len(raw)
    if w <= 0 or h <= 0 or buf_size <= 0:
        return None

    fourcc_name = ""
    try:
        fc = vf.get_fourcc()
        fourcc_name = getattr(fc, "name", str(fc))
    except Exception:
        pass

    try:
        # UYVY ≈ 2 bytes/pixel; BGRA = 4 bytes/pixel (check BGRA first if buffer is large enough)
        min_bgra = w * h * 4
        min_uyvy = w * h * 2
        if buf_size >= min_bgra or "BGRA" in fourcc_name or "BGRX" in fourcc_name:
            need = min_bgra
            if buf_size < need:
                return None
            img = Image.frombuffer("RGBA", (w, h), raw[:need], "raw", "BGRA", 0, 1).convert("RGB")
        elif "UYVY" in fourcc_name or (buf_size >= min_uyvy and buf_size < min_bgra):
            rgb = _uyvy_to_rgb_bytes(raw[:min_uyvy], w, h)
            if not rgb:
                return None
            img = Image.frombytes("RGB", (w, h), rgb)
        else:
            _log(f"Unsupported NDI video layout: fourcc={fourcc_name!r} w={w} h={h} buf={buf_size}")
            return None
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
    except Exception as e:
        _log(f"JPEG encode error ({fourcc_name}): {e}")
        return None


def _make_receiver(source=None, source_name: Optional[str] = None):
    """Create Receiver with DistroAV-like defaults (highest bandwidth, UYVY_BGRA, named recv)."""
    from cyndilib.receiver import Receiver

    kwargs = {}
    try:
        from cyndilib.wrapper.ndi_recv import RecvBandwidth, RecvColorFormat

        kwargs["color_format"] = RecvColorFormat.UYVY_BGRA
        kwargs["bandwidth"] = RecvBandwidth.highest
        kwargs["allow_video_fields"] = True
        kwargs["recv_name"] = "HA-NDI-Bridge"
    except Exception:
        pass

    if source is not None:
        return Receiver(source=source, **kwargs)
    return Receiver(source_name=source_name or "", **kwargs)


# ---------------------------------------------------------------------------
# Receiver loop
# ---------------------------------------------------------------------------

def receiver_loop():
    global latest_jpeg
    try:
        from cyndilib.receiver import ReceiveFrameType
    except ImportError as e:
        _log(f"Import error in receiver_loop: {e}")
        return

    recv: Optional[Receiver] = None
    connected_to: Optional[str] = None
    first_frame_logged = False
    last_wait_log = 0.0
    logged_invalid_frame = False

    _log("Receiver loop started")

    while True:
        with current_source_lock:
            src_name = current_source_name

        if not src_name:
            if recv is not None:
                try:
                    recv.disconnect()
                except Exception:
                    pass
                recv = None
                connected_to = None
                first_frame_logged = False
            time.sleep(0.5)
            continue

        if recv is None or connected_to != src_name:
            if recv is not None:
                try:
                    recv.disconnect()
                except Exception:
                    pass
                recv = None
                connected_to = None
                first_frame_logged = False
                last_wait_log = 0.0
                logged_invalid_frame = False

            # First try via Finder (has Source object = better reconnection)
            finder = _get_finder()
            src_obj = finder.get_source(src_name) if finder else None

            try:
                if src_obj is not None:
                    recv = _make_receiver(source=src_obj)
                    _log(f"Receiver connected via Finder: {src_name!r}")
                else:
                    recv = _make_receiver(source_name=src_name)
                    _log(f"Receiver connecting by name (no Finder match): {src_name!r}")
                connected_to = src_name
                last_wait_log = time.time()
            except Exception as e:
                _log(f"Receiver create error: {e}")
                recv = None
                time.sleep(2)
                continue

        try:
            if not first_frame_logged and (time.time() - last_wait_log) >= 15.0:
                last_wait_log = time.time()
                _log("Waiting for first video frame from receiver (source may not be sending yet)")

            result = recv.receive(ReceiveFrameType.recv_video, timeout_ms=3000)
            if result & ReceiveFrameType.recv_video:
                vf = recv.video_frame
                if vf is not None:
                    w, h = vf.get_resolution()
                    buf_size = vf.get_buffer_size()
                    if buf_size > 0 and w > 0 and h > 0:
                        raw = bytearray(buf_size)
                        vf.fill_p_data(memoryview(raw))
                        jpeg = _video_frame_to_jpeg(vf, bytes(raw), quality=85)
                        if jpeg is None:
                            continue
                        with latest_jpeg_lock:
                            latest_jpeg = jpeg
                        if not first_frame_logged:
                            first_frame_logged = True
                            _log("First frame received — snapshot available")
                        for q in mjpeg_subscribers[:]:
                            try:
                                q.put_nowait(jpeg)
                            except Exception:
                                pass
                    elif not logged_invalid_frame:
                        logged_invalid_frame = True
                        _log(f"receive() returned video but frame invalid: w={w} h={h} buf_size={buf_size}")
                elif not logged_invalid_frame:
                    logged_invalid_frame = True
                    _log("receive() returned video flag but video_frame is None")
        except Exception as e:
            _log(f"Frame error: {e}")
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

async def handle_sources(_request: web.Request) -> web.Response:
    """GET /sources — list of discovered NDI source names."""
    loop = asyncio.get_event_loop()
    names = await loop.run_in_executor(None, get_sources_sync)
    return web.json_response({"sources": names})


async def handle_scan(_request: web.Request) -> web.Response:
    """GET /scan — force fresh discovery and return current sources (non-blocking)."""
    loop = asyncio.get_event_loop()
    names = await loop.run_in_executor(None, scan_sources_sync)
    return web.json_response({"sources": names, "scanned": True})


async def handle_get_source(_request: web.Request) -> web.Response:
    """GET /source — current source name."""
    with current_source_lock:
        name = current_source_name or ""
    return web.json_response({"source_name": name})


async def handle_set_source(request: web.Request) -> web.Response:
    """POST /source — set current NDI source. Body: {"source_name": "..."}"""
    global current_source_name
    try:
        body = await request.json()
        name = body.get("source_name", "")
    except Exception:
        name = ""
    with current_source_lock:
        current_source_name = name if name else None
    _log(f"Source set to: {current_source_name!r}")
    return web.json_response({"source_name": current_source_name or ""})


async def handle_snapshot(_request: web.Request) -> web.Response:
    """GET /snapshot.jpg — latest JPEG frame."""
    with latest_jpeg_lock:
        jpeg = latest_jpeg
    if jpeg is None:
        raise web.HTTPServiceUnavailable(reason="No frame available yet")
    return web.Response(body=jpeg, content_type="image/jpeg")


async def handle_stream_mjpeg(request: web.Request) -> web.Response:
    """GET /stream.mjpg — MJPEG multipart stream."""
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "multipart/x-mixed-replace; boundary=--ndibridge",
            "Cache-Control": "no-cache",
        },
    )
    await response.prepare(request)

    q: asyncio.Queue = asyncio.Queue(maxsize=2)
    mjpeg_subscribers.append(q)
    try:
        with latest_jpeg_lock:
            first = latest_jpeg
        if first:
            await _write_mjpeg_frame(response, first)

        while True:
            try:
                jpeg = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                with latest_jpeg_lock:
                    jpeg = latest_jpeg
                if jpeg:
                    await _write_mjpeg_frame(response, jpeg)
                continue
            await _write_mjpeg_frame(response, jpeg)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        if q in mjpeg_subscribers:
            mjpeg_subscribers.remove(q)
    return response


async def _write_mjpeg_frame(response: web.StreamResponse, jpeg: bytes) -> None:
    await response.write(
        b"--ndibridge\r\nContent-Type: image/jpeg\r\nContent-Length: "
        + str(len(jpeg)).encode()
        + b"\r\n\r\n"
    )
    await response.write(jpeg)
    await response.write(b"\r\n")


async def handle_health(_request: web.Request) -> web.Response:
    """GET /health — liveness + diagnostic info."""
    with current_source_lock:
        src = current_source_name or ""
    with latest_jpeg_lock:
        has_frame = latest_jpeg is not None
    finder = _finder  # non-locking read for status
    return web.json_response({
        "status": "ok",
        "source": src,
        "streaming": has_frame,
        "finder_open": finder is not None and getattr(finder, "is_open", False),
        "num_sources": finder.num_sources if finder else 0,
        "log": _discovery_log[-10:],
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    options = load_options()
    port = options["port"]

    global current_source_name
    current_source_name = options["source_name"] or None

    # Configure NDI Discovery Server if provided (bypasses mDNS)
    if options.get("discovery_server"):
        _configure_ndi_discovery_server(options["discovery_server"])
    else:
        # Fall back to Avahi/mDNS
        _ensure_avahi()

    # Start the Finder in background (returns quickly; no long sleep)
    threading.Thread(target=_get_finder, daemon=True).start()
    # Log discovery result after 3s in a separate thread so /sources never blocks
    threading.Thread(target=_log_initial_discovery, daemon=True).start()

    # Start receiver loop
    threading.Thread(target=receiver_loop, daemon=True).start()

    app = web.Application()
    app.router.add_get("/sources", handle_sources)
    app.router.add_get("/scan", handle_scan)
    app.router.add_get("/source", handle_get_source)
    app.router.add_post("/source", handle_set_source)
    app.router.add_get("/stream.mjpg", handle_stream_mjpeg)
    app.router.add_get("/snapshot.jpg", handle_snapshot)
    app.router.add_get("/health", handle_health)

    _log(f"NDI Bridge listening on 0.0.0.0:{port}")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
