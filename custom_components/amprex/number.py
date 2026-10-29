"""amprex numbers (hold target)."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
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
    setup_platform_entities(hass, entry, async_add_entities, "number", AmprexNumber)


class AmprexNumber(AmprexEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, hub: AmprexHub, spec: protocol.Entity) -> None:
        super().__init__(hub, spec)
        self._attr_native_unit_of_measurement = spec.unit
        if spec.min_value is not None:
            self._attr_native_min_value = spec.min_value
        if spec.max_value is not None:
            self._attr_native_max_value = spec.max_value
        if spec.step is not None:
            self._attr_native_step = spec.step
        try:
            self._attr_device_class = (
                NumberDeviceClass(spec.device_class) if spec.device_class else None
            )
        except ValueError:
            self._attr_device_class = None

    @property
    def native_value(self) -> float | None:
        value = self.value
        return float(value) if isinstance(value, int | float) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.command(value)
