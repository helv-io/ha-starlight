"""Diagnostics with the Bluetooth address removed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .const import CONF_PRODUCT_ID, DOMAIN

TO_REDACT = {CONF_ADDRESS, "mac", "address"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for one light."""
    device = hass.data[DOMAIN][entry.entry_id]
    state = device.state
    data = {
        "product_id": device.product_id,
        "kind": device.kind,
        "model": device.model,
        "ble_version": device.ble_version,
        "firmware": device.firmware,
        "header_version": device.header_version,
        "connected": device.connected,
        "available": device.available,
        "rssi": state.rssi,
        "is_on": state.is_on,
        "brightness": state.brightness,
        "effect": state.effect,
        "color_mode": state.color_mode,
        "last_error": device.last_error,
        "entry_product_id": entry.data.get(CONF_PRODUCT_ID),
    }
    return async_redact_data(data, TO_REDACT)
