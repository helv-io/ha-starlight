"""Sweep buttons for stair lights."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import StarlightDevice
from .entity import StarlightEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sweep buttons."""
    device: StarlightDevice = hass.data[DOMAIN][entry.entry_id]
    if device.kind != "stair":
        return
    async_add_entities(
        [
            SweepButton(device, "sweep_down", "down", "mdi:arrow-down-bold"),
            SweepButton(device, "sweep_up", "up", "mdi:arrow-up-bold"),
        ]
    )


class SweepButton(StarlightEntity, ButtonEntity):
    """Run the stairs in one direction."""

    def __init__(self, device: StarlightDevice, key: str, direction: str, icon: str) -> None:
        super().__init__(device)
        self._direction = direction
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_unique_id = f"{device.address}_{key}"

    async def async_press(self) -> None:
        await self._device.async_sweep(self._direction)
