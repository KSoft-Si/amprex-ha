"""amprex selects (hold scope and duration, away)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AmprexConfigEntry
from .entity import AmprexEntity, setup_platform_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmprexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_platform_entities(hass, entry, async_add_entities, "select", AmprexSelect)


class AmprexSelect(AmprexEntity, SelectEntity):
    @property
    def options(self) -> list[str]:
        return list(self.spec.options or ())

    @property
    def current_option(self) -> str | None:
        value = self.value
        return value if isinstance(value, str) and value in self.options else None

    async def async_select_option(self, option: str) -> None:
        await self.command(option)
