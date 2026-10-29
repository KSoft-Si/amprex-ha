"""amprex sensors from the manifest."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
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
    setup_platform_entities(hass, entry, async_add_entities, "sensor", AmprexSensor)


class AmprexSensor(AmprexEntity, SensorEntity):
    def __init__(self, hub: AmprexHub, spec: protocol.Entity) -> None:
        super().__init__(hub, spec)
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_device_class = _enum(SensorDeviceClass, spec.device_class)
        self._attr_state_class = _enum(SensorStateClass, spec.state_class)
        if self._attr_device_class is SensorDeviceClass.ENUM and spec.options:
            self._attr_options = list(spec.options)

    @property
    def native_value(self) -> Any:
        value = self.value
        if self._attr_device_class is SensorDeviceClass.TIMESTAMP:
            return protocol.parse_time(value)
        if isinstance(value, dict | list):
            return None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.attrs


def _enum(kind: Any, value: str | None) -> Any:
    try:
        return kind(value) if value else None
    except ValueError:
        return None
