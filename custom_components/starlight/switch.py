"""Switches for the motion sensor, soft start, and microphone."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    """Set up switches."""
    device: StarlightDevice = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = []
    if device.kind == "stair":
        entities.append(
            FlagSwitch(device, "induction", "mdi:motion-sensor", device.async_set_induction)
        )
        entities.append(
            FlagSwitch(device, "slow_open", "mdi:speedometer-slow", device.async_set_slow)
        )
    if device.supports_music:
        entities.append(
            FlagSwitch(device, "mic", "mdi:microphone", device.async_set_mic, "microphone")
        )
    async_add_entities(entities)


class FlagSwitch(StarlightEntity, SwitchEntity):
    """A boolean sent to the controller."""

    def __init__(
        self,
        device: StarlightDevice,
        key: str,
        icon: str,
        setter,
        translation_key: str | None = None,
    ) -> None:
        super().__init__(device)
        self._key = key
        self._setter = setter
        self._attr_icon = icon
        self._attr_translation_key = translation_key or key
        self._attr_unique_id = f"{device.address}_{key}"

    @property
    def is_on(self) -> bool:
        return bool(getattr(self._device.state, self._key))

    async def async_turn_on(self, **kwargs) -> None:
        await self._setter(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._setter(False)
