"""Camera platform for NDI Camera integration."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_BRIDGE_URL, CONF_CAMERA_NAME, CONF_SOURCE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Time for bridge to switch source and receive first frame (NDI can be slow to connect)
_SOURCE_SWITCH_DELAY = 5.0
_SNAPSHOT_RETRY_DELAY = 3.0
_SNAPSHOT_RETRIES = 5
_MIN_JPEG_BYTES = 100


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NDI Camera from a config entry."""
    data = config_entry.data
    bridge_url = data[CONF_BRIDGE_URL].rstrip("/")
    source_name = data[CONF_SOURCE_NAME]
    name = data.get(CONF_CAMERA_NAME, source_name)

    async_add_entities(
        [NdiCameraEntity(hass, config_entry.entry_id, name, bridge_url, source_name)]
    )


class NdiCameraEntity(Camera):
    """NDI camera: polls MJPEG snapshot from the NDI Bridge addon."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        name: str,
        bridge_url: str,
        source_name: str,
    ) -> None:
        super().__init__()
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}-{source_name}"
        self._bridge_url = bridge_url
        self._source_name = source_name

    async def _set_bridge_source(self) -> bool:
        """Tell the bridge to stream this camera's NDI source. Required before snapshot."""
        url = f"{self._bridge_url}/source"
        try:
            session = async_get_clientsession(self.hass)
            async with session.post(
                url,
                json={"source_name": self._source_name},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                ok = resp.status == 200
                if not ok:
                    _LOGGER.warning(
                        "NDI Camera %s: set source failed %s from %s",
                        self._attr_name,
                        resp.status,
                        self._bridge_url,
                    )
                return ok
        except Exception as e:
            _LOGGER.warning(
                "NDI Camera %s: cannot reach bridge at %s: %s",
                self._attr_name,
                self._bridge_url,
                e,
            )
            return False

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return the latest JPEG snapshot from the bridge."""
        if not await self._set_bridge_source():
            return None
        await asyncio.sleep(_SOURCE_SWITCH_DELAY)

        url = f"{self._bridge_url}/snapshot.jpg"
        for attempt in range(_SNAPSHOT_RETRIES):
            try:
                session = async_get_clientsession(self.hass)
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if len(data) >= _MIN_JPEG_BYTES and data[:2] == b"\xff\xd8":
                            return data
                        _LOGGER.warning(
                            "NDI Camera %s: snapshot invalid (size=%s, not JPEG)",
                            self._attr_name,
                            len(data),
                        )
                    elif resp.status == 503:
                        if attempt < _SNAPSHOT_RETRIES - 1:
                            await asyncio.sleep(_SNAPSHOT_RETRY_DELAY)
                            continue
                        _LOGGER.warning(
                            "NDI Camera %s: bridge still has no frame after %s tries (503). "
                            "Check NDI Bridge app log for 'Receiver connected' and 'Frame error'. "
                            "Is the NDI source actually sending?",
                            self._attr_name,
                            _SNAPSHOT_RETRIES,
                        )
                    else:
                        _LOGGER.warning(
                            "NDI Camera %s: snapshot %s from %s",
                            self._attr_name,
                            resp.status,
                            url,
                        )
            except Exception as e:
                _LOGGER.warning(
                    "NDI Camera %s: snapshot fetch error: %s",
                    self._attr_name,
                    e,
                )
            break
        return None

    @property
    def mjpeg_url(self) -> str:
        """MJPEG stream URL (informational, used by the camera card)."""
        return f"{self._bridge_url}/stream.mjpg"
