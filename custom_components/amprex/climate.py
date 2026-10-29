"""amprex thermostats: setting a target starts a hold for that scope."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AmprexConfigEntry, protocol
from .const import DOMAIN
from .entity import AmprexEntity, setup_platform_entities
from .hub import AmprexHub

_ATTRIBUTE_KEYS = ("source", "zone_id", "hold_id", "active_until", "away_active")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmprexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_platform_entities(hass, entry, async_add_entities, "climate", AmprexClimate)


class AmprexClimate(AmprexEntity, ClimateEntity):
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    # Comfort control is switched on and off in amprex, not from HA.
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    def __init__(self, hub: AmprexHub, spec: protocol.Entity) -> None:
        super().__init__(hub, spec)
        if spec.min_value is not None:
            self._attr_min_temp = spec.min_value
        if spec.max_value is not None:
            self._attr_max_temp = spec.max_value
        if spec.step is not None:
            self._attr_target_temperature_step = spec.step

    @property
    def hvac_mode(self) -> HVACMode | None:
        return HVACMode.HEAT if self.value == "heat" else HVACMode.OFF

    @property
    def native_current_temperature(self) -> float | None:
        return _float(self.attrs.get("current_temperature"))

    @property
    def native_target_temperature(self) -> float | None:
        return _float(self.attrs.get("target_temperature"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = self.attrs
        return {
            "comfort_low": attrs.get("target_temp_low"),
            "comfort_high": attrs.get("target_temp_high"),
            **{key: attrs.get(key) for key in _ATTRIBUTE_KEYS},
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.command(float(temperature))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="hvac_mode_not_supported"
        )


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
