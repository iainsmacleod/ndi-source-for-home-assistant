"""
NDI Bridge: HTTP server that discovers NDI sources and streams selected source as MJPEG.
API: GET /sources, POST /source, GET /stream.mjpg
"""
import asyncio
import io
import json
import os
import threading
from typing import Optional

import aiohttp
from aiohttp import web

# Optional: load options from Home Assistant addon config
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


# Global state
current_source_name: Optional[str] = None
current_source_lock = threading.Lock()
latest_jpeg: Optional[bytes] = None
latest_jpeg_lock = threading.Lock()
mjpeg_subscribers: list = []  # list of asyncio.Queue
receiver_thread: Optional[threading.Thread] = None
receiver_stop = threading.Event()


def get_sources_sync() -> list[str]:
    try:
        from cyndilib.finder import Finder

        with Finder() as finder:
            finder.open()
            import time
            time.sleep(2)  # allow discovery
            return list(finder.get_source_names())
    except Exception as e:
        print(f"Discovery error: {e}")
        return []


def receiver_loop():
    """Background thread: receive NDI frames, convert to JPEG, push to subscribers."""
    global latest_jpeg
    try:
        from cyndilib.finder import Finder
        from cyndilib.receiver import Receiver, ReceiveFrameType
        from cyndilib.wrapper.ndi_recv import RecvColorFormat
        from PIL import Image
    except ImportError as e:
        print(f"Import error in receiver_loop: {e}")
        return

    recv = None
    finder = None

    while not receiver_stop.is_set():
        with current_source_lock:
            src_name = current_source_name

        if not src_name:
            recv = None
            if finder is None:
                finder = Finder()
                finder.open()
            import time
            time.sleep(0.5)
            continue

        if recv is None or recv.source_name != src_name:
            if recv is not None:
                try:
                    recv.disconnect()
                except Exception:
                    pass
                recv = None
            if finder is None:
                finder = Finder()
                finder.open()
            src = finder.get_source(src_name)
            if src is None:
                import time
                time.sleep(1)
                continue
            recv = Receiver(source=src, color_format=RecvColorFormat.BGRA)
            recv.set_source(src)

        if recv is None:
            continue

        result = recv.receive(ReceiveFrameType.recv_video, timeout_ms=1000)
        if result == ReceiveFrameType.recv_video and recv.video_frame is not None:
            vf = recv.video_frame
            try:
                w, h = vf.get_resolution()
                buf_size = vf.get_buffer_size()
                if buf_size > 0 and w > 0 and h > 0:
                    raw = bytearray(buf_size)
                    vf.fill_p_data(memoryview(raw))
                    # Convert raw BGRA bytes to RGB JPEG without numpy.
                    img = Image.frombuffer(
                        "RGBA",
                        (w, h),
                        bytes(raw),
                        "raw",
                        "BGRA",
                        0,
                        1,
                    ).convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    jpeg = buf.getvalue()
                    with latest_jpeg_lock:
                        latest_jpeg = jpeg
                    for q in mjpeg_subscribers[:]:
                        try:
                            q.put_nowait(jpeg)
                        except asyncio.QueueFull:
                            pass
            except Exception as e:
                print(f"Frame error: {e}")

    if recv is not None:
        try:
            recv.disconnect()
        except Exception:
            pass
    if finder is not None:
        try:
            finder.close()
        except Exception:
            pass


async def handle_sources(_request: web.Request) -> web.Response:
    """GET /sources: return list of NDI source names."""
    loop = asyncio.get_event_loop()
    names = await loop.run_in_executor(None, get_sources_sync)
    return web.json_response({"sources": names})


async def handle_set_source(request: web.Request) -> web.Response:
    """POST /source: set current NDI source. Body: {"source_name": "..."}."""
    global current_source_name
    try:
        body = await request.json()
        name = body.get("source_name", "")
    except Exception:
        name = ""
    with current_source_lock:
        current_source_name = name if name else None
    return web.json_response({"source_name": current_source_name or ""})


async def handle_get_source(_request: web.Request) -> web.Response:
    """GET /source: return current source name."""
    with current_source_lock:
        name = current_source_name or ""
    return web.json_response({"source_name": name})


async def handle_stream_mjpeg(request: web.Request) -> web.Response:
    """GET /stream.mjpg: MJPEG stream (multipart/x-mixed-replace)."""
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
        # Send initial frame if we have one
        with latest_jpeg_lock:
            if latest_jpeg:
                await response.write(
                    b"--ndibridge\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(latest_jpeg)).encode()
                    + b"\r\n\r\n"
                )
                await response.write(latest_jpeg)
                await response.write(b"\r\n")

        while True:
            try:
                jpeg = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send last frame again to keep connection alive
                with latest_jpeg_lock:
                    if latest_jpeg:
                        await response.write(
                            b"--ndibridge\r\nContent-Type: image/jpeg\r\nContent-Length: "
                            + str(len(latest_jpeg)).encode()
                            + b"\r\n\r\n"
                        )
                        await response.write(latest_jpeg)
                        await response.write(b"\r\n")
                continue
            await response.write(
                b"--ndibridge\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(jpeg)).encode()
                + b"\r\n\r\n"
            )
            await response.write(jpeg)
            await response.write(b"\r\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        if q in mjpeg_subscribers:
            mjpeg_subscribers.remove(q)
    return response


async def handle_health(_request: web.Request) -> web.Response:
    """GET /health: liveness."""
    return web.json_response({"status": "ok"})


def main():
    options = load_options()
    port = options["port"]
    global current_source_name
    current_source_name = options["source_name"] or None

    global receiver_thread
    receiver_thread = threading.Thread(target=receiver_loop, daemon=True)
    receiver_thread.start()

    app = web.Application()
    app.router.add_get("/sources", handle_sources)
    app.router.add_get("/source", handle_get_source)
    app.router.add_post("/source", handle_set_source)
    app.router.add_get("/stream.mjpg", handle_stream_mjpeg)
    app.router.add_get("/health", handle_health)

    print(f"NDI Bridge listening on 0.0.0.0:{port}")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
