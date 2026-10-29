"""amprex buttons (start hold, resume schedule, comfort feedback)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AmprexConfigEntry
from .entity import AmprexEntity, setup_platform_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmprexConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_platform_entities(hass, entry, async_add_entities, "button", AmprexButton)


class AmprexButton(AmprexEntity, ButtonEntity):
    async def async_press(self) -> None:
        await self.command()
