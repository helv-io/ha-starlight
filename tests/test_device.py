"""Device decisions that do not need a radio."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.starlight.const import CONF_BLE_VERSION, CONF_PRODUCT_ID, DOMAIN
from custom_components.starlight.device import StarlightDevice
from custom_components.starlight.number import StairCountNumber
from custom_components.starlight.protocol.products import get_product, known_product_ids, load_tables
from homeassistant.const import CONF_ADDRESS, CONF_NAME


@pytest.fixture(autouse=True)
def _bluetooth_dependencies():
    """Satisfy the bluetooth dependency chain without a local adapter."""
    with (
        patch("homeassistant.components.usb.async_setup", return_value=True),
        patch("homeassistant.components.bluetooth.async_setup", return_value=True),
        patch("homeassistant.components.bluetooth_adapters.async_setup", return_value=True),
        patch("custom_components.starlight.async_register_callback", return_value=lambda: None),
        patch(
            "custom_components.starlight.device.bluetooth.async_address_present",
            return_value=True,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the integration from this repo."""
    yield


def _products():
    return [product for pid in known_product_ids() if (product := get_product(pid)) is not None]


def _entry(hass, data: dict):
    entry = MockConfigEntry(domain=DOMAIN, data=data, unique_id=data[CONF_ADDRESS])
    entry.add_to_hass(hass)
    return entry


async def test_unknown_product_is_rgb_v0(hass) -> None:
    entry = _entry(hass, {CONF_ADDRESS: "AA:BB:CC:DD:EE:FF"})
    device = StarlightDevice(hass, entry)
    assert device.kind == "rgb"
    assert device.header_version == 0
    assert device.model == "Color light"


async def test_stair_effects_and_header(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    wide = next(product for product in _products() if "stair_16_32" in product.functions)
    narrow = next(
        product
        for product in _products()
        if product.kind == "stair" and "stair_16_32" not in product.functions
    )
    assert wide.kind == "stair" and wide.channels == 32
    assert narrow.channels == 16
    entry = _entry(
        hass,
        {
            CONF_ADDRESS: "AA:BB:CC:DD:EE:10",
            CONF_PRODUCT_ID: wide.product_id,
            CONF_BLE_VERSION: 7,
        },
    )
    device = StarlightDevice(hass, entry)
    assert device.kind == "stair"
    assert device.header_version == 0
    assert device.model == "Stair light 32"
    assert device.state.stair_count == 32
    assert len(device.effect_options()) == 16
    assert len(device.effect_options(tab_only=True)) < 16
    device._set_effect_local("Stream")
    assert device.state.tab == "stream"
    assert device.state.mode_key == "stream"
    assert "Stream" in device.effect_options(tab_only=True)
    device._handle_notify(bytes.fromhex("00"))
    assert device.state.last_notify == "00"
    assert StairCountNumber(device).entity_registry_enabled_default is False


async def test_stair_entry_exposes_effects(hass) -> None:
    """A stair product from the table sets up a light whose effects are the full list."""
    await hass.async_add_executor_job(load_tables)
    wide = next(product for product in _products() if "stair_16_32" in product.functions)
    entry = _entry(
        hass,
        {
            CONF_ADDRESS: "AA:BB:CC:DD:EE:11",
            CONF_NAME: "Stairs",
            CONF_PRODUCT_ID: wide.product_id,
            CONF_BLE_VERSION: 7,
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("light.stairs")
    assert state is not None
    assert state.state == "off"
    effects = state.attributes["effect_list"]
    assert len(effects) == 16
    assert "Step by step" in effects
    assert "Full" in effects
    assert hass.states.get("sensor.stairs_signal_strength") is not None
    assert hass.states.get("sensor.stairs_last_notification") is not None
    assert hass.states.get("select.stairs_effect_tab") is not None
