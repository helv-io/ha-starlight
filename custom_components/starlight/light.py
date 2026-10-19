"""Light entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MAX_KELVIN, MIN_KELVIN
from .device import StarlightDevice
from .entity import StarlightEntity
from .protocol.rgb import SOLID


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the light."""
    async_add_entities([StarlightLight(hass.data[DOMAIN][entry.entry_id])])


class StarlightLight(StarlightEntity, LightEntity):
    """The light itself."""

    _attr_name = None

    def __init__(self, device: StarlightDevice) -> None:
        super().__init__(device)
        self._attr_unique_id = device.address

    @property
    def is_on(self) -> bool:
        return self._device.state.is_on

    @property
    def brightness(self) -> int:
        return self._device.state.brightness

    @property
    def hs_color(self) -> tuple[float, float] | None:
        if not self._device.supports_color:
            return None
        return self._device.state.hs

    @property
    def color_temp_kelvin(self) -> int | None:
        if not self._device.supports_color_temp:
            return None
        return self._device.state.color_temp

    @property
    def min_color_temp_kelvin(self) -> int:
        return MIN_KELVIN

    @property
    def max_color_temp_kelvin(self) -> int:
        return MAX_KELVIN

    @property
    def color_mode(self) -> ColorMode:
        if self._device.state.color_mode == "color_temp" and self._device.supports_color_temp:
            return ColorMode.COLOR_TEMP
        if self._device.supports_color:
            return ColorMode.HS
        if self._device.kind == "cct":
            return ColorMode.COLOR_TEMP
        return ColorMode.BRIGHTNESS

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        modes: set[ColorMode] = set()
        if self._device.supports_color:
            modes.add(ColorMode.HS)
        if self._device.supports_color_temp:
            modes.add(ColorMode.COLOR_TEMP)
        return modes or {ColorMode.BRIGHTNESS}

    @property
    def supported_features(self) -> LightEntityFeature:
        if self._device.supports_effects:
            return LightEntityFeature.EFFECT
        return LightEntityFeature(0)

    @property
    def effect_list(self) -> list[str] | None:
        if not self._device.supports_effects:
            return None
        return self._device.effect_options()

    @property
    def effect(self) -> str | None:
        if self._device.kind == "stair":
            return self._device.stair_mode.label
        return self._device.state.effect or SOLID

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._device.async_turn_on(
            brightness=kwargs.get(ATTR_BRIGHTNESS, self._device.state.brightness),
            hs_color=kwargs.get(ATTR_HS_COLOR),
            color_temp_kelvin=kwargs.get(ATTR_COLOR_TEMP_KELVIN),
            effect=kwargs.get(ATTR_EFFECT),
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.async_turn_off()
