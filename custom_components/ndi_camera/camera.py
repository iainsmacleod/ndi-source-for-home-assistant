"""Camera platform for NDI Camera integration."""

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_BRIDGE_URL, CONF_NAME, CONF_SOURCE_NAME, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NDI Camera from a config entry."""
    data = config_entry.data
    bridge_url = data[CONF_BRIDGE_URL].rstrip("/")
    source_name = data[CONF_SOURCE_NAME]
    name = data.get(CONF_NAME, "NDI Camera")

    async_add_entities(
        [NdiCameraEntity(config_entry.entry_id, name, bridge_url, source_name)]
    )


class NdiCameraEntity(Camera):
    """Representation of an NDI camera stream."""

    _attr_name = None  # we set it from config

    def __init__(
        self,
        entry_id: str,
        name: str,
        bridge_url: str,
        source_name: str,
    ) -> None:
        """Initialize the NDI camera."""
        super().__init__()
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}-{source_name}"
        self._bridge_url = bridge_url
        self._source_name = source_name

    @property
    def stream_source(self) -> str:
        """Return the stream source URL (MJPEG from the bridge)."""
        return f"{self._bridge_url}/stream.mjpg"
