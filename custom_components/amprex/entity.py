"""Base entity built from one manifest entry."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol
from .const import DOMAIN
from .hub import AmprexHub

if TYPE_CHECKING:
    from . import AmprexConfigEntry


class AmprexEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: AmprexHub, spec: protocol.Entity) -> None:
        self.hub = hub
        self.spec = spec
        self._attr_unique_id = f"{hub.controller_id}_{spec.key}"
        self._attr_name = spec.name
        if spec.icon:
            self._attr_icon = spec.icon
        if spec.entity_category in ("config", "diagnostic"):
            self._attr_entity_category = EntityCategory(spec.entity_category)
        manifest = hub.manifest
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.controller_id)},
            name=manifest.name if manifest else "amprex",
            manufacturer=manifest.manufacturer if manifest else "KSoft",
            model=manifest.model if manifest else None,
            sw_version=manifest.sw_version if manifest else None,
            serial_number=hub.controller_id,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.listen_entity(self.spec.key, self._updated))
        self.async_on_remove(self.hub.listen_manifest(self._manifest_changed))

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()

    @callback
    def _manifest_changed(self, manifest: protocol.Manifest) -> None:
        spec = next((item for item in manifest.entities if item.key == self.spec.key), None)
        if spec is not None:
            self.spec = spec

    @property
    def in_manifest(self) -> bool:
        manifest = self.hub.manifest
        return manifest is not None and self.spec.key in manifest.keys

    @property
    def state_data(self) -> protocol.State | None:
        return self.hub.states.get(self.spec.key)

    @property
    def value(self) -> Any:
        state = self.state_data
        return None if state is None else state.value

    @property
    def attrs(self) -> dict[str, Any]:
        state = self.state_data
        return {} if state is None else state.attributes

    @property
    def available(self) -> bool:
        if not (self.hub.connected and self.hub.online and self.in_manifest):
            return False
        if self.spec.state_topic is None:
            return True  # buttons
        state = self.state_data
        return state is not None and state.fresh(
            self.spec.expire_after_s, datetime.now(timezone.utc)
        )

    async def command(self, value: float | str | None = None) -> None:
        await self.hub.async_command(self.spec.key, value)


def setup_platform_entities(
    hass: HomeAssistant,
    entry: AmprexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    platform: str,
    factory: Callable[[AmprexHub, protocol.Entity], AmprexEntity],
) -> None:
    """Add this platform's manifest entities now and whenever new ones appear."""
    hub = entry.runtime_data
    added: set[str] = set()

    @callback
    def add(manifest: protocol.Manifest) -> None:
        new = [
            spec
            for spec in manifest.entities
            if spec.platform == platform and spec.key not in added
        ]
        added.update(spec.key for spec in new)
        if new:
            async_add_entities([factory(hub, spec) for spec in new])

    if hub.manifest is not None:
        add(hub.manifest)
    entry.async_on_unload(hub.listen_manifest(add))
