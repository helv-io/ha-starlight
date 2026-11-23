"""Symphony (hc category) controllers: E1 21 effects, EC 03 music, EA 81 state.

The state uploads are real ones captured from a pre-lit tree (product 197)
after each command was sent.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.starlight.const import CONF_BLE_VERSION, CONF_PRODUCT_ID, DOMAIN
from custom_components.starlight.device import StarlightDevice
from custom_components.starlight.protocol import symphony
from custom_components.starlight.protocol.products import (
    get_product,
    known_product_ids,
    load_tables,
)
from custom_components.starlight.protocol.rgb import MICROPHONE, power_payload
from custom_components.starlight.protocol.state import decode_payload
from custom_components.starlight.protocol.transport import build_frame
from homeassistant.const import CONF_ADDRESS

# Captured EA 81 uploads.
STATIC_RED = "EA810000C508232414500000646400000001150000000146010015"
STATIC_HUE_247 = "EA810000C50823241464007BE4640000000115000000014601001500"
STATIC_BLUE_248 = "EA810000C50823241464007C646400000001150000000146010015"
OFF = "EA810000C50824241464007C646400000001150000000146010015"
EFFECT_9_SPEED_80 = "EA810000C50823250950007C646400000001150000000146010015"
MUSIC = "EA810000C508236201500000646400000001150000000146010015"
# Raw FF02 notification exactly as the tree sent it (JSON wrapper, opcode 0x0A).
RAW_NOTIFY = (
    "04868000004d4e0a7b22636f6465223a302c227061796c6f6164223a2245413831303030304335303832"
    "33323431343634303037433634363430303030303030313135303030303030303134363031303031"
    "35227d"
)


def _symphony_products():
    load_tables()
    return [
        product
        for pid in known_product_ids()
        if (product := get_product(pid)) is not None and symphony.is_symphony(product)
    ]


def test_symphony_detection_is_data_driven() -> None:
    products = _symphony_products()
    assert products
    assert all(product.category.startswith("hc") for product in products)
    stairs = [
        get_product(pid)
        for pid in known_product_ids()
        if get_product(pid) and get_product(pid).kind == "stair"
    ]
    assert stairs
    assert not any(symphony.is_symphony(product) for product in stairs)


def test_power_uses_bare_3b() -> None:
    product = next(p for p in _symphony_products() if p.supports("switch_led_v2"))
    off = power_payload(product, False)
    on = power_payload(product, True)
    assert off[:2] == bytes.fromhex("3b24")
    assert on[:2] == bytes.fromhex("3b23")
    assert off[-1] == sum(off[:-1]) & 0xFF


def test_effect_payload_layout() -> None:
    payload = symphony.effect_payload(9, 80, 100, [(120.0, 100.0)], density=50)
    assert payload.hex() == "e12100640900013250" + "00" * 6 + "01" + "3c64640000"


def test_effect_payload_palette_and_limits() -> None:
    colors = symphony.palette_colors("Christmas", (10.0, 50.0))
    payload = symphony.effect_payload(1, 0, 0, colors)
    assert payload[3] == 1  # brightness never 0
    assert payload[8] == 1  # speed never 0
    assert payload[15] == len(colors)
    assert len(payload) == 16 + 5 * len(colors)
    assert symphony.palette_colors(symphony.CURRENT_COLOR, (10.0, 50.0)) == [(10.0, 50.0)]


def test_music_payload_layout() -> None:
    payload = symphony.music_payload(1, 100, 100, [(240.0, 100.0), (0.0, 100.0)])
    assert payload.hex() == "ec03016401006402" + "7864640000" + "0064640000"


def test_effect_names_match_app() -> None:
    assert symphony.EFFECTS[1] == "Wave"
    assert symphony.EFFECTS[20] == "Superluminal"
    assert symphony.EFFECTS[102] == "Static Fill"
    assert len(symphony.EFFECTS) == 24


@pytest.mark.parametrize(
    ("raw", "is_on", "hs", "effect_id", "mic"),
    [
        (STATIC_RED, True, (0.0, 100.0), None, False),
        (STATIC_BLUE_248, True, (248.0, 100.0), None, False),
        (STATIC_HUE_247, True, (247.0, 100.0), None, False),
        (OFF, False, (248.0, 100.0), None, False),
        (EFFECT_9_SPEED_80, True, None, 9, False),
        (MUSIC, True, None, None, True),
    ],
)
def test_state_decode(raw, is_on, hs, effect_id, mic) -> None:
    product = _symphony_products()[0]
    decoded = decode_payload(bytes.fromhex(raw), product)
    assert decoded.is_on is is_on
    assert decoded.hs == hs
    assert decoded.effect_id == effect_id
    assert decoded.mic is mic


@pytest.fixture(autouse=True)
def _bluetooth_dependencies():
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
    yield


def _device(hass) -> StarlightDevice:
    product = _symphony_products()[0]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ADDRESS: "AA:BB:CC:DD:EE:42",
            CONF_PRODUCT_ID: product.product_id,
            CONF_BLE_VERSION: 7,
        },
        unique_id="AA:BB:CC:DD:EE:42",
    )
    entry.add_to_hass(hass)
    return StarlightDevice(hass, entry)


def _notify(payload_hex: str, seq: int) -> bytes:
    body = json.dumps({"code": 0, "payload": payload_hex}).encode()
    return build_frame(body, 0, seq, 0x0A)


async def test_device_effects_and_state(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    device = _device(hass)
    options = device.effect_options()
    assert options[0] == "Solid"
    assert "Superluminal" in options
    assert "Scene 1" not in options
    device._handle_notify(bytes.fromhex(RAW_NOTIFY))
    assert device.state.is_on is True
    assert device.state.hs == (248.0, 100.0)
    device._handle_notify(_notify(EFFECT_9_SPEED_80, 2))
    assert device.state.effect == "Breathe"
    assert device.state.effect_speed == 80
    device._handle_notify(_notify(MUSIC, 3))
    assert device.state.effect == MICROPHONE
    assert device.state.mic is True
    device._handle_notify(_notify(OFF, 4))
    assert device.state.is_on is False
    assert device.state.mic is False


async def test_device_sends_symphony_commands(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    device = _device(hass)
    sent: list[bytes] = []

    async def _send(payload, opcode):
        sent.append(payload)
        return payload

    device._send = _send
    await device.async_turn_on(effect="Comet")
    assert sent[0][:2] == bytes.fromhex("3b23")
    assert sent[1][:2] == bytes.fromhex("e121")
    assert sent[1][4] == 17
    await device.async_set_music_mode(3)
    assert sent[-1][:2] == bytes.fromhex("ec03")
    assert sent[-1][4] == 3
    await device.async_set_mic(False)
    assert sent[-1][:2] == bytes.fromhex("3ba1")
    await device.async_turn_off()
    assert sent[-1][:2] == bytes.fromhex("3b24")


async def test_density_reaches_effect(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    device = _device(hass)
    sent: list[bytes] = []

    async def _send(payload, opcode):
        sent.append(payload)
        return payload

    device._send = _send
    await device.async_turn_on(effect="Meteor")
    await device.async_set_density(80)
    assert sent[-1][:2] == bytes.fromhex("e121")
    assert sent[-1][7] == 80
