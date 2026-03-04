"""Config flow for NDI Camera integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_BRIDGE_URL,
    CONF_CAMERA_NAME,
    CONF_SOURCE_NAME,
    DEFAULT_BRIDGE_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def _check_bridge(bridge_url: str) -> tuple[bool, list[str]]:
    """
    Returns (reachable, sources).
    reachable=False means cannot connect at all.
    reachable=True, sources=[] means connected but no NDI sources found yet.
    """
    url = f"{bridge_url.rstrip('/')}/sources"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return False, []
                data = await resp.json()
                return True, list(data.get("sources", []))
    except Exception as e:
        _LOGGER.warning("Failed to fetch NDI sources from %s: %s", url, e)
        return False, []


async def set_bridge_source(bridge_url: str, source_name: str) -> bool:
    """Tell the bridge which NDI source to stream."""
    url = f"{bridge_url.rstrip('/')}/source"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"source_name": source_name},
                timeout=aiohttp.ClientTimeout(total=5),
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
        """Step 1: enter Bridge URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_BRIDGE_URL].strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                url = f"http://{url}"
            self._bridge_url = url

            reachable, sources = await _check_bridge(self._bridge_url)

            if not reachable:
                errors["base"] = "cannot_reach_bridge"
            elif not sources:
                # Bridge is up but discovery is empty — let user proceed with manual entry
                return await self.async_step_manual_source()
            else:
                self._sources = sources
                return await self.async_step_select_source()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_BRIDGE_URL, default=DEFAULT_BRIDGE_URL): str}
            ),
            errors=errors,
        )

    async def async_step_select_source(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2a: pick from discovered NDI sources."""
        if user_input is not None:
            return await self._finish(
                user_input[CONF_SOURCE_NAME],
                user_input.get(CONF_CAMERA_NAME, "") or user_input[CONF_SOURCE_NAME],
            )

        return self.async_show_form(
            step_id="select_source",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE_NAME): vol.In(self._sources),
                    vol.Optional(CONF_CAMERA_NAME, default="NDI Camera"): str,
                }
            ),
        )

    async def async_step_manual_source(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2b: no sources discovered — let user type source name manually."""
        errors: dict[str, str] = {}

        if user_input is not None:
            source_name = user_input.get(CONF_SOURCE_NAME, "").strip()
            if not source_name:
                errors[CONF_SOURCE_NAME] = "source_name_required"
            else:
                return await self._finish(
                    source_name,
                    user_input.get(CONF_CAMERA_NAME, "") or source_name,
                )

        return self.async_show_form(
            step_id="manual_source",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE_NAME, default=""): str,
                    vol.Optional(CONF_CAMERA_NAME, default="NDI Camera"): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "hint": "No NDI sources were discovered. "
                "Check multicast/mDNS networking, or enter the source name manually "
                "(format: 'HOSTNAME (SOURCE NAME)')."
            },
        )

    async def _finish(self, source_name: str, camera_name: str) -> FlowResult:
        """Create the config entry."""
        await set_bridge_source(self._bridge_url, source_name)

        await self.async_set_unique_id(f"{self._bridge_url}#{source_name}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=camera_name,
            data={
                CONF_BRIDGE_URL: self._bridge_url,
                CONF_SOURCE_NAME: source_name,
                CONF_CAMERA_NAME: camera_name,
            },
        )
