"""Config flow for Starlight."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_BLE_VERSION,
    CONF_DISCONNECT_DELAY,
    CONF_FIRMWARE,
    CONF_HEADER_VERSION,
    CONF_PRODUCT_ID,
    DEFAULT_DISCONNECT_DELAY,
    DEFAULT_HEADER_VERSION,
    DOMAIN,
    HEADER_AUTO,
)
from .device import friendly_name
from .protocol.advert import parse_service_info
from .protocol.products import get_product

_MAC = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def _model_for(product_id: int | None, fallback: str = "Color light") -> str:
    product = get_product(product_id)
    if product is None:
        return fallback
    if product.kind == "stair" and product.channels:
        return f"Stair light {product.channels}"
    return product.model


class StarlightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle discovery and manual setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._advert = None

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> FlowResult:
        """Handle a device found by the bluetooth integration."""
        advert = parse_service_info(discovery_info)
        if advert is None or not advert.product_id:
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self._advert = advert
        name = friendly_name(discovery_info.name, _model_for(advert.product_id))
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm a discovered light."""
        assert self._discovery is not None
        advert = self._advert
        name = friendly_name(
            self._discovery.name,
            _model_for(advert.product_id if advert else None),
        )
        if user_input is not None:
            return self._create(self._discovery.address, name, advert)
        self.context["title_placeholders"] = {"name": name}
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": name,
                "model": _model_for(advert.product_id if advert else None),
            },
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick a discovered light or type an address."""
        discovered = self._discover()
        if user_input is not None:
            manual = (user_input.get("manual_address") or "").strip().upper()
            chosen = user_input.get("address")
            if manual:
                if not _MAC.match(manual):
                    return self._user_form(discovered, {"manual_address": "invalid_address"})
                await self.async_set_unique_id(manual)
                self._abort_if_unique_id_configured()
                known = discovered.get(manual)
                name = friendly_name(
                    known[0].name if known else None,
                    _model_for(known[1].product_id if known else None),
                )
                return self._create(manual, name, known[1] if known else None)
            if not chosen or chosen not in discovered:
                return self._user_form(discovered, {"address": "no_device"})
            info, advert = discovered[chosen]
            await self.async_set_unique_id(info.address)
            self._abort_if_unique_id_configured()
            name = friendly_name(info.name, _model_for(advert.product_id))
            return self._create(info.address, name, advert)
        return self._user_form(discovered, None)

    def _discover(self) -> dict[str, tuple[BluetoothServiceInfoBleak, Any]]:
        found: dict[str, tuple[BluetoothServiceInfoBleak, Any]] = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            advert = parse_service_info(info)
            if advert is None or not advert.product_id:
                continue
            found[info.address] = (info, advert)
        return found

    def _user_form(self, discovered: dict, errors: dict | None) -> FlowResult:
        choices = {
            address: friendly_name(info.name, _model_for(advert.product_id))
            for address, (info, advert) in discovered.items()
        }
        schema: dict[Any, Any] = {}
        if choices:
            schema[vol.Optional(CONF_ADDRESS)] = vol.In(choices)
        schema[vol.Optional("manual_address")] = str
        return self.async_show_form(step_id="user", data_schema=vol.Schema(schema), errors=errors)

    def _create(self, address: str, name: str, advert) -> FlowResult:
        data = {
            CONF_ADDRESS: address,
            CONF_NAME: name,
            CONF_PRODUCT_ID: advert.product_id if advert else None,
            CONF_BLE_VERSION: advert.ble_version if advert else None,
            CONF_FIRMWARE: advert.firmware if advert else None,
        }
        return self.async_create_entry(title=name, data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return StarlightOptionsFlow()


class StarlightOptionsFlow(OptionsFlow):
    """Frame version and idle disconnect."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_HEADER_VERSION,
                        default=options.get(CONF_HEADER_VERSION, DEFAULT_HEADER_VERSION),
                    ): vol.In([HEADER_AUTO, "0", "1"]),
                    vol.Optional(
                        CONF_DISCONNECT_DELAY,
                        default=options.get(CONF_DISCONNECT_DELAY, DEFAULT_DISCONNECT_DELAY),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=300)),
                }
            ),
        )
