"""amprex binary sensors from the manifest."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AmprexConfigEntry, protocol
from .entity import AmprexEntity, setup_platform_entities
from .hub import AmprexHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmprexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_platform_entities(hass, entry, async_add_entities, "binary_sensor", AmprexBinarySensor)


class AmprexBinarySensor(AmprexEntity, BinarySensorEntity):
    def __init__(self, hub: AmprexHub, spec: protocol.Entity) -> None:
        super().__init__(hub, spec)
        try:
            self._attr_device_class = (
                BinarySensorDeviceClass(spec.device_class) if spec.device_class else None
            )
        except ValueError:
            self._attr_device_class = None

    @property
    def is_on(self) -> bool | None:
        value = self.value
        return value if isinstance(value, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.attrs
