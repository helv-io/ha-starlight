"""Starlight lights on local Bluetooth."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothServiceInfoBleak,
    async_register_callback,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.service import async_extract_config_entry_ids

from .const import BLOCKED_EF, DOMAIN, STATE_POLL_SECONDS
from .device import StarlightDevice
from .protocol.advert import parse_service_info
from .protocol.products import load_tables

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register services once."""
    await hass.async_add_executor_job(load_tables)
    hass.data.setdefault(DOMAIN, {})

    async def _devices(call) -> list[StarlightDevice]:
        entry_ids = await async_extract_config_entry_ids(hass, call)
        if not entry_ids:
            entry_ids = set(hass.data[DOMAIN])
        return [
            hass.data[DOMAIN][entry_id] for entry_id in entry_ids if entry_id in hass.data[DOMAIN]
        ]

    async def handle_sweep(call) -> None:
        direction = call.data["direction"]
        for device in await _devices(call):
            if device.kind != "stair":
                continue
            await device.async_sweep(direction)

    async def handle_send_payload(call) -> None:
        text = call.data["payload"].replace(",", " ").replace("0x", "")
        try:
            payload = bytes.fromhex(text)
        except ValueError as err:
            raise HomeAssistantError("Payload is not hex") from err
        if not payload:
            raise HomeAssistantError("Payload is empty")
        force = bool(call.data.get("force"))
        if not force and len(payload) >= 2 and payload[0] == 0xEF and payload[1] in BLOCKED_EF:
            raise HomeAssistantError(
                "That command changes install data. Turn on Allow install commands to send it."
            )
        for device in await _devices(call):
            await device.async_send_payload(payload)

    hass.services.async_register(DOMAIN, "sweep", handle_sweep)
    hass.services.async_register(DOMAIN, "send_payload", handle_send_payload)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one light."""
    await hass.async_add_executor_job(load_tables)
    device = StarlightDevice(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = device

    @callback
    def _on_advert(service_info: BluetoothServiceInfoBleak, _change: BluetoothChange) -> None:
        advert = parse_service_info(service_info)
        if advert is None:
            if service_info.rssi is not None:
                device.state.rssi = service_info.rssi
                device._notify()
            return
        device.apply_advert(advert)

    unregister = async_register_callback(
        hass,
        _on_advert,
        BluetoothCallbackMatcher(address=device.address),
        BluetoothChange.ADVERTISEMENT,
    )

    async def _poll_state(_now) -> None:
        await device.async_request_state()

    entry.async_on_unload(unregister)
    entry.async_on_unload(
        async_track_time_interval(hass, _poll_state, timedelta(seconds=STATE_POLL_SECONDS))
    )
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one light."""
    device: StarlightDevice | None = hass.data[DOMAIN].pop(entry.entry_id, None)
    if device is not None:
        await device.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
