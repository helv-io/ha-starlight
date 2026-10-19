"""Device decisions that do not need a radio."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.starlight.const import (
    CONF_BLE_VERSION,
    CONF_FIRMWARE,
    CONF_PRODUCT_ID,
    DOMAIN,
    STATE_POLL_SECONDS,
)
from custom_components.starlight.device import StarlightDevice
from custom_components.starlight.diagnostics import async_get_config_entry_diagnostics
from custom_components.starlight.number import StairCountNumber
from custom_components.starlight.protocol.advert import parse_service_info
from custom_components.starlight.protocol.products import (
    get_product,
    known_product_ids,
    load_tables,
)
from custom_components.starlight.protocol.rgb import brightness_to_percent
from custom_components.starlight.protocol.transport import build_frame
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.util import dt as dt_util


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


def _notify_frame() -> bytes:
    payload = bytes.fromhex("ea810100140123000000f000646464640100")
    return build_frame(payload, 0, 1, 0x15)


async def test_notify_and_advert_update_entities(hass) -> None:
    """A live 0x15 reply fills the light and the summary. Adverts do not replace it."""
    await hass.async_add_executor_job(load_tables)
    wide = next(product for product in _products() if "stair_16_32" in product.functions)
    entry = _entry(
        hass,
        {
            CONF_ADDRESS: "AA:BB:CC:DD:EE:12",
            CONF_NAME: "Stairs",
            CONF_PRODUCT_ID: wide.product_id,
            CONF_BLE_VERSION: 7,
            CONF_FIRMWARE: "15",
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = hass.data[DOMAIN][entry.entry_id]
    device._handle_notify(_notify_frame())
    await hass.async_block_till_done()

    assert device.state.last_summary == "on, Full, 100%"
    assert device.state.last_fields["opcode"] == "0x15"
    assert device.state.last_fields["raw"] == _notify_frame().hex()
    assert device.state.last_fields["effect"] == "Full"
    assert device.state.last_fields["motion"] is False
    assert device.state.last_fields["soft_start"] is False
    assert device.state.is_on is True
    assert device.state.mode_key == "full"
    assert device.state.tab == "time"
    assert brightness_to_percent(device.state.brightness) == 100
    assert device.state.hs == (200.0, 100.0)

    light = hass.states.get("light.stairs")
    assert light is not None
    assert light.state == "on"
    assert light.attributes["effect"] == "Full"
    assert light.attributes["brightness"] == device.state.brightness
    sensor = hass.states.get("sensor.stairs_last_notification")
    assert sensor is not None
    assert sensor.state == "on, Full, 100%"
    assert sensor.attributes["raw"] == _notify_frame().hex()
    assert sensor.attributes["effect"] == "Full"

    state = bytes.fromhex("8023030000f03c645f645f01006420000f235f0103000500640000")
    identity = bytes.fromhex("8007aabbccddeeff021415010101")
    advert = parse_service_info(
        SimpleNamespace(
            manufacturer_data={0x5A02: state},
            service_data={"00005a02-0000-1000-8000-00805f9b34fb": identity},
            name="IOTBT65B",
            rssi=-87,
        )
    )
    assert advert is not None
    device.apply_advert(advert)
    await hass.async_block_till_done()
    assert device.state.last_summary == "on, Full, 100%"
    assert device.state.last_advert_fields["brightness"] == 95
    assert device.state.last_advert_fields["motion"] is True
    assert device.state.last_advert_fields["soft_start"] is True
    assert device.state.induction is True
    assert device.state.slow_open is True
    assert brightness_to_percent(device.state.brightness) == 95
    sensor = hass.states.get("sensor.stairs_last_notification")
    assert sensor is not None
    assert sensor.state == "on, Full, 100%"
    assert sensor.attributes["effect"] == "Full"

    device._handle_notify(bytes.fromhex("00"))
    assert device.state.last_summary == "on, Full, 100%"
    assert device.state.last_notify == "00"
    assert device.state.last_fields["raw"] == "00"

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["last_notify_summary"] == "on, Full, 100%"
    assert diag["last_notify_fields"]["effect"] == "Full"
    assert diag["last_advert_fields"]["soft_start"] is True
    assert diag["motion"] is True
    assert diag["soft_start"] is True


async def test_rgb_notify_sets_color_and_effect(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    product = next(item for item in _products() if item.kind == "rgb")
    entry = _entry(
        hass,
        {
            CONF_ADDRESS: "AA:BB:CC:DD:EE:13",
            CONF_PRODUCT_ID: product.product_id,
            CONF_BLE_VERSION: 8,
        },
    )
    device = StarlightDevice(hass, entry)
    color = bytes.fromhex("811d2361f000ff00000002003000")
    device._handle_notify(build_frame(color, 1, 1, 0x15))
    assert device.state.is_on is True
    assert device.state.effect is None
    assert device.state.hs[0] == pytest.approx(0.0)
    assert device.state.hs[1] == pytest.approx(100.0)
    effect = bytes.fromhex("8100232530640000000000000000")
    device._handle_notify(build_frame(effect, 1, 2, 0x0C))
    assert device.state.effect == "Strobe"
    assert brightness_to_percent(device.state.brightness) == 100
    assert device.state.last_summary == "on, Strobe, 100%"


async def test_state_poll_runs_on_interval(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    wide = next(product for product in _products() if "stair_16_32" in product.functions)
    entry = _entry(
        hass,
        {
            CONF_ADDRESS: "AA:BB:CC:DD:EE:14",
            CONF_NAME: "Stairs",
            CONF_PRODUCT_ID: wide.product_id,
            CONF_BLE_VERSION: 7,
        },
    )
    with patch.object(StarlightDevice, "async_request_state", new_callable=AsyncMock) as query:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=STATE_POLL_SECONDS))
        await hass.async_block_till_done()
        assert query.await_count >= 1
