"""
NDI Bridge: HTTP server that discovers NDI sources and streams selected source as MJPEG.
API: GET /sources, POST /source, GET /stream.mjpg, GET /snapshot.jpg, GET /health
"""
import asyncio
import io
import json
import os
import threading
import time
from typing import Optional

from aiohttp import web

OPTIONS_PATH = "/data/options.json"


def load_options() -> dict:
    out = {"port": 8080, "source_name": ""}
    out["port"] = int(os.environ.get("NDI_BRIDGE_PORT", "8080"))
    out["source_name"] = os.environ.get("NDI_BRIDGE_SOURCE_NAME", "")
    if os.path.isfile(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH) as f:
                data = json.load(f)
                out["port"] = int(data.get("port", out["port"]))
                out["source_name"] = data.get("source_name", out["source_name"])
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
current_source_name: Optional[str] = None
current_source_lock = threading.Lock()

latest_jpeg: Optional[bytes] = None
latest_jpeg_lock = threading.Lock()

mjpeg_subscribers: list = []

# Single persistent Finder shared by discovery + receiver
_finder = None
_finder_lock = threading.Lock()
_finder_ready = threading.Event()


def _get_finder():
    """Return the global Finder, creating and opening it if needed."""
    global _finder
    with _finder_lock:
        if _finder is None:
            try:
                from cyndilib.finder import Finder
                _finder = Finder()
                _finder.open()
                # Wait a few seconds for initial discovery
                time.sleep(5)
                _finder_ready.set()
            except Exception as e:
                print(f"Finder init error: {e}")
                _finder = None
        return _finder


def get_sources_sync() -> list[str]:
    """Return currently known NDI source names."""
    try:
        finder = _get_finder()
        if finder is None:
            return []
        return list(finder.get_source_names())
    except Exception as e:
        print(f"Discovery error: {e}")
        return []


# ---------------------------------------------------------------------------
# Receiver loop
# ---------------------------------------------------------------------------

def receiver_loop():
    """Background thread: receive NDI frames, convert to JPEG, push to subscribers."""
    global latest_jpeg
    try:
        from cyndilib.receiver import Receiver, ReceiveFrameType
        from PIL import Image
    except ImportError as e:
        print(f"Import error in receiver_loop: {e}")
        return

    # Wait for the finder to be ready before we start trying to connect
    _finder_ready.wait(timeout=15)

    recv: Optional[Receiver] = None
    connected_to: Optional[str] = None

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
            time.sleep(0.5)
            continue

        finder = _get_finder()

        if recv is None or connected_to != src_name:
            if recv is not None:
                try:
                    recv.disconnect()
                except Exception:
                    pass
                recv = None
                connected_to = None

            if finder is None:
                time.sleep(1)
                continue

            src = finder.get_source(src_name)
            if src is None:
                time.sleep(1)
                continue

            try:
                recv = Receiver(source=src)
                connected_to = src_name
                print(f"Receiver connected to: {src_name}")
            except Exception as e:
                print(f"Receiver create error: {e}")
                recv = None
                time.sleep(1)
                continue

        try:
            result = recv.receive(ReceiveFrameType.recv_video, timeout_ms=1000)
            if result & ReceiveFrameType.recv_video:
                vf = recv.video_frame
                if vf is not None:
                    w, h = vf.get_resolution()
                    buf_size = vf.get_buffer_size()
                    if buf_size > 0 and w > 0 and h > 0:
                        raw = bytearray(buf_size)
                        vf.fill_p_data(memoryview(raw))
                        img = Image.frombuffer(
                            "RGBA", (w, h), bytes(raw), "raw", "BGRA", 0, 1
                        ).convert("RGB")
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85)
                        jpeg = buf.getvalue()
                        with latest_jpeg_lock:
                            latest_jpeg = jpeg
                        for q in mjpeg_subscribers[:]:
                            try:
                                q.put_nowait(jpeg)
                            except Exception:
                                pass
        except Exception as e:
            print(f"Frame error: {e}")
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

async def handle_sources(_request: web.Request) -> web.Response:
    """GET /sources — list of discovered NDI source names."""
    loop = asyncio.get_event_loop()
    names = await loop.run_in_executor(None, get_sources_sync)
    return web.json_response({"sources": names})


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
    print(f"Source set to: {current_source_name!r}")
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
    """GET /health — liveness."""
    with current_source_lock:
        src = current_source_name or ""
    with latest_jpeg_lock:
        has_frame = latest_jpeg is not None
    return web.json_response({
        "status": "ok",
        "source": src,
        "streaming": has_frame,
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    options = load_options()
    port = options["port"]

    global current_source_name
    current_source_name = options["source_name"] or None

    # Start the persistent finder in background so it's ready fast
    threading.Thread(target=_get_finder, daemon=True).start()

    # Start receiver loop
    threading.Thread(target=receiver_loop, daemon=True).start()

    app = web.Application()
    app.router.add_get("/sources", handle_sources)
    app.router.add_get("/source", handle_get_source)
    app.router.add_post("/source", handle_set_source)
    app.router.add_get("/stream.mjpg", handle_stream_mjpeg)
    app.router.add_get("/snapshot.jpg", handle_snapshot)
    app.router.add_get("/health", handle_health)

    print(f"NDI Bridge listening on 0.0.0.0:{port}")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
