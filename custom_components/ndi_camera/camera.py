"""Camera platform for NDI Camera integration."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_BRIDGE_URL, CONF_CAMERA_NAME, CONF_SOURCE_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


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

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return the latest JPEG snapshot from the bridge."""
        url = f"{self._bridge_url}/snapshot.jpg"
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
                _LOGGER.debug("Snapshot returned %s from %s", resp.status, url)
        except Exception as e:
            _LOGGER.debug("Snapshot fetch error from %s: %s", url, e)
        return None

    @property
    def mjpeg_url(self) -> str:
        """MJPEG stream URL (informational, used by the camera card)."""
        return f"{self._bridge_url}/stream.mjpg"
