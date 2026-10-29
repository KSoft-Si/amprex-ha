"""The amprex integration: amprex controller state and thermostat control over MQTT.

Entities come from the controller's retained manifest only; this package
defines none of its own.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_ADDRESS,
    CONF_CERTIFICATE,
    CONF_CONTROLLER_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    EXPIRY_CHECK_S,
    MANIFEST_TIMEOUT_S,
)
from .hub import AmprexHub
from .pairing import Pairing, build_tls_context

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]

type AmprexConfigEntry = ConfigEntry[AmprexHub]


def pairing_from_entry(data: dict) -> Pairing:
    return Pairing(
        controller_id=data[CONF_CONTROLLER_ID],
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        server_certificate_pem=data[CONF_CERTIFICATE],
    )


async def async_setup_entry(hass: HomeAssistant, entry: AmprexConfigEntry) -> bool:
    pairing = pairing_from_entry(dict(entry.data))
    tls = await hass.async_add_executor_job(
        build_tls_context, pairing.server_certificate_pem, pairing.host
    )
    hub = AmprexHub(
        hass,
        pairing,
        entry.data.get(CONF_ADDRESS) or pairing.host,
        tls,
        on_auth_failure=lambda: entry.async_start_reauth(hass),
    )
    task = entry.async_create_background_task(hass, hub.run(), f"amprex {pairing.controller_id}")
    try:
        async with asyncio.timeout(MANIFEST_TIMEOUT_S):
            await hub.manifest_ready.wait()
    except TimeoutError as exc:
        task.cancel()
        raise ConfigEntryNotReady(
            f"No manifest from amprex {pairing.controller_id} yet"
        ) from exc
    entry.runtime_data = hub
    entry.async_on_unload(
        async_track_time_interval(
            hass, lambda _now: hub.notify_all(), timedelta(seconds=EXPIRY_CHECK_S)
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AmprexConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
