"""Number entities for stair timing and effect speed."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import StarlightDevice
from .entity import StarlightEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numbers."""
    device: StarlightDevice = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []
    if device.kind == "stair":
        entities.extend(
            [
                StairCountNumber(device),
                StairTimeNumber(device, "run_time", "run_time", device.async_set_run_time),
                StairTimeNumber(device, "hold_time", "hold_time", device.async_set_hold_time),
            ]
        )
    elif device.supports_effects:
        entities.append(EffectSpeedNumber(device))
    if device.supports_music:
        entities.append(SensitivityNumber(device))
    async_add_entities(entities)


class _Number(StarlightEntity, NumberEntity):
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1


class StairCountNumber(_Number):
    """How many steps the controller drives."""

    _attr_translation_key = "stair_count"
    _attr_icon = "mdi:stairs"
    _attr_native_min_value = 1
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, device: StarlightDevice) -> None:
        super().__init__(device)
        self._attr_unique_id = f"{device.address}_stair_count"
        self._attr_native_max_value = float(device.product.channels if device.product else 32)

    @property
    def native_value(self) -> float:
        return float(self._device.state.stair_count)

    async def async_set_native_value(self, value: float) -> None:
        await self._device.async_set_stair_count(int(value))


class StairTimeNumber(_Number):
    """A time-tab value. The unit on the wire is unverified, so none is shown."""

    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 100

    def __init__(self, device: StarlightDevice, key: str, translation_key: str, setter) -> None:
        super().__init__(device)
        self._attr_unique_id = f"{device.address}_{key}"
        self._attr_translation_key = translation_key
        self._key = key
        self._setter = setter

    @property
    def native_value(self) -> float:
        return float(getattr(self._device.state, self._key))

    async def async_set_native_value(self, value: float) -> None:
        await self._setter(int(value))


class EffectSpeedNumber(_Number):
    """How fast the current effect runs."""

    _attr_translation_key = "effect_speed"
    _attr_icon = "mdi:speedometer"
    _attr_native_min_value = 1
    _attr_native_max_value = 100

    def __init__(self, device: StarlightDevice) -> None:
        super().__init__(device)
        self._attr_unique_id = f"{device.address}_speed"

    @property
    def native_value(self) -> float:
        return float(self._device.state.effect_speed)

    async def async_set_native_value(self, value: float) -> None:
        await self._device.async_set_speed(int(value))


class SensitivityNumber(_Number):
    """Microphone sensitivity."""

    _attr_translation_key = "mic_sensitivity"
    _attr_icon = "mdi:microphone"
    _attr_native_min_value = 1
    _attr_native_max_value = 100

    def __init__(self, device: StarlightDevice) -> None:
        super().__init__(device)
        self._attr_unique_id = f"{device.address}_sensitivity"

    @property
    def native_value(self) -> float:
        return float(self._device.state.mic_sensitivity)

    async def async_set_native_value(self, value: float) -> None:
        await self._device.async_set_sensitivity(int(value))
