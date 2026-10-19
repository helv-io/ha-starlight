"""Signal strength and the last notification."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import StarlightEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up signal and last-notification sensors."""
    device = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RssiSensor(device), LastNotifySensor(device)])


class RssiSensor(StarlightEntity, SensorEntity):
    """Latest advertisement RSSI."""

    _attr_translation_key = "rssi"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_registry_enabled_default = True

    def __init__(self, device) -> None:
        super().__init__(device)
        self._attr_unique_id = f"{device.address}_rssi"

    @property
    def native_value(self) -> int | None:
        return self._device.state.rssi


class LastNotifySensor(StarlightEntity, SensorEntity):
    """Readable summary of the last GATT notification."""

    _attr_translation_key = "last_notify"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:message-reply-text"

    def __init__(self, device) -> None:
        super().__init__(device)
        self._attr_unique_id = f"{device.address}_last_notify"

    @property
    def native_value(self) -> str | None:
        value = self._device.state.last_summary
        if value is not None and len(value) > 255:
            return value[:255]
        return value

    @property
    def extra_state_attributes(self) -> dict | None:
        if not self._device.state.last_fields:
            return None
        return dict(self._device.state.last_fields)
