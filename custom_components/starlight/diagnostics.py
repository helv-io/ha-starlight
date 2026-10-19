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
        "last_notify": state.last_notify,
        "last_notify_summary": state.last_summary,
        "last_notify_fields": state.last_fields,
        "last_advert_fields": state.last_advert_fields,
        "is_on": state.is_on,
        "motion": state.induction,
        "soft_start": state.slow_open,
        "run_time": state.run_time,
        "hold_time": state.hold_time,
        "tab": state.tab,
        "brightness": state.brightness,
        "effect": state.effect,
        "color_mode": state.color_mode,
        "last_error": device.last_error,
        "entry_product_id": entry.data.get(CONF_PRODUCT_ID),
    }
    return async_redact_data(data, TO_REDACT)
