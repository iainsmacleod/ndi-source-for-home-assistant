"""Config flow for NDI Camera integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_BRIDGE_URL, CONF_SOURCE_NAME, DEFAULT_BRIDGE_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def fetch_sources(bridge_url: str) -> list[str]:
    """Fetch NDI source names from the bridge. Returns empty list on error."""
    url = f"{bridge_url.rstrip('/')}/sources"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return list(data.get("sources", []))
    except Exception as e:
        _LOGGER.warning("Failed to fetch NDI sources from %s: %s", url, e)
        return []


async def set_bridge_source(bridge_url: str, source_name: str) -> bool:
    """Tell the bridge to stream the given source."""
    url = f"{bridge_url.rstrip('/')}/source"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json={"source_name": source_name}, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return resp.status == 200
    except Exception as e:
        _LOGGER.warning("Failed to set NDI source: %s", e)
        return False


class NdiCameraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NDI Camera."""

    VERSION = 1

    def __init__(self) -> None:
        self._bridge_url = DEFAULT_BRIDGE_URL
        self._sources: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step: bridge URL then source selection."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_BRIDGE_URL, default=DEFAULT_BRIDGE_URL
                        ): str,
                    }
                ),
                description_placeholders={
                    "bridge_help": "URL of the NDI Bridge addon (e.g. http://localhost:8080). "
                    "Ensure the addon is installed and running with host network.",
                },
            )

        self._bridge_url = user_input[CONF_BRIDGE_URL].strip().rstrip("/")
        if not self._bridge_url.startswith(("http://", "https://")):
            self._bridge_url = f"http://{self._bridge_url}"

        sources = await fetch_sources(self._bridge_url)
        if not sources:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_BRIDGE_URL, default=self._bridge_url
                        ): str,
                    }
                ),
                errors={"base": "cannot_reach_bridge"},
                description_placeholders={"bridge_help": ""},
            )

        self._sources = sources
        return await self.async_step_select_source()

    async def async_step_select_source(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let user select an NDI source and optional name."""
        if user_input is None:
            return self.async_show_form(
                step_id="select_source",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_SOURCE_NAME): vol.In(self._sources),
                        vol.Optional(CONF_NAME, default="NDI Camera"): str,
                    }
                ),
            )

        source_name = user_input[CONF_SOURCE_NAME]
        friendly_name = user_input.get(CONF_NAME, "NDI Camera") or "NDI Camera"

        await set_bridge_source(self._bridge_url, source_name)

        await self.async_set_unique_id(f"{self._bridge_url}#{source_name}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=friendly_name,
            data={
                CONF_BRIDGE_URL: self._bridge_url,
                CONF_SOURCE_NAME: source_name,
                CONF_NAME: friendly_name,
            },
        )
