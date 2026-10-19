"""Select entities for stair tabs, stair modes, and power-on color."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import StarlightDevice
from .entity import StarlightEntity
from .protocol.stair import TABS

_TAB_LABELS = {"step": "Step", "stream": "Stream", "time": "Time"}
_TAB_FROM_LABEL = {label: key for key, label in _TAB_LABELS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up selects."""
    device: StarlightDevice = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []
    if device.kind == "stair":
        entities.append(StairTabSelect(device))
        entities.append(StairModeSelect(device))
    else:
        entities.append(PowerOnSelect(device))
    async_add_entities(entities)


class StairTabSelect(StarlightEntity, SelectEntity):
    """Step, stream, or time."""

    _attr_translation_key = "effect_tab"
    _attr_icon = "mdi:tab"

    def __init__(self, device: StarlightDevice) -> None:
        super().__init__(device)
        self._attr_unique_id = f"{device.address}_tab"

    @property
    def options(self) -> list[str]:
        return list(_TAB_LABELS.values())

    @property
    def current_option(self) -> str | None:
        return _TAB_LABELS.get(self._device.state.tab, "Step")

    async def async_select_option(self, option: str) -> None:
        tab = _TAB_FROM_LABEL.get(option, option if option in TABS else "step")
        await self._device.async_set_tab(tab)


class StairModeSelect(StarlightEntity, SelectEntity):
    """Effect for the current tab."""

    _attr_translation_key = "effect"
    _attr_icon = "mdi:palette"

    def __init__(self, device: StarlightDevice) -> None:
        super().__init__(device)
        self._attr_unique_id = f"{device.address}_mode"

    @property
    def options(self) -> list[str]:
        return self._device.effect_options(tab_only=True)

    @property
    def current_option(self) -> str | None:
        return self._device.stair_mode.label

    async def async_select_option(self, option: str) -> None:
        await self._device.async_set_effect(option)


class PowerOnSelect(StarlightEntity, SelectEntity):
    """Whether the next color is kept after power returns."""

    _attr_translation_key = "power_on"
    _attr_icon = "mdi:power-settings"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["Temporary", "Remember"]

    def __init__(self, device: StarlightDevice) -> None:
        super().__init__(device)
        self._attr_unique_id = f"{device.address}_power_on"

    @property
    def current_option(self) -> str | None:
        return "Remember" if self._device.state.remember else "Temporary"

    async def async_select_option(self, option: str) -> None:
        await self._device.async_set_remember(option == "Remember")
