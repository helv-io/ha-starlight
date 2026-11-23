"""Symphony (hc category) controllers: E1 21 effects, EC 03 music, EA 81 state.

The state uploads are real ones captured from a pre-lit tree (product 197)
after each command was sent.
"""

from __future__ import annotations

import asyncio
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


# Captured from the tree: E0 06 with no timers, and after slot 6 was written.
TIMERS_EMPTY = (
    "E00601"
    + "000000000000"
    + "02"
    + "000000000000"
    + "03"
    + "000000000000"
    + ("04" + "000000000000" + "05" + "000000000000" + "06" + "000000000000")
)
TIMERS_SLOT6_OFF = (
    "E006010000000000000200000000000003000000000000040000000000000500000000000006"
    "F0080800FE0EE001002400000000000000000000"
)
# Music mode picked on the IR remote: mode 0x62, id 6.
MUSIC_FROM_REMOTE = "EA810000C50823620632006D326400000001150000000146010015"


def test_timer_payloads_match_capture() -> None:
    payload = symphony.timer_slot_payload(6, 8, 8, symphony.REPEAT_DAILY, False)
    assert payload.hex() == "e00506f0080800fe0ee001002400000000000000000000"
    assert symphony.clear_slot_payload(6).hex() == "e00506" + "00" * 20


def test_set_time_matches_capture() -> None:
    from datetime import datetime

    payload = symphony.set_time_payload(datetime(2026, 11, 23, 8, 5, 57))
    assert payload.hex() == "10141a0b170805390100a7"


def test_parse_timers() -> None:
    assert symphony.parse_timers(bytes.fromhex(TIMERS_EMPTY)) == {}
    slots = symphony.parse_timers(bytes.fromhex(TIMERS_SLOT6_OFF))
    assert slots == {6: symphony.TimerSlot(6, 8, 8, 0xFE, False)}
    assert symphony.timer_option(slots, symphony.TIMER_OFF) == symphony.TIMER_6H
    daily = dict(slots)
    daily[5] = symphony.TimerSlot(5, 2, 8, 0xFE, True)
    assert symphony.timer_option(daily, symphony.TIMER_OFF) == symphony.TIMER_DAILY
    assert symphony.timer_option({}, symphony.TIMER_DAILY) == symphony.TIMER_OFF


async def test_timer_select_programs_slots(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    device = _device(hass)
    device.state.is_on = True
    sent: list[bytes] = []

    async def _send(payload, opcode):
        sent.append(payload)
        return payload

    device._send = _send
    await device.async_set_timer(symphony.TIMER_DAILY)
    assert sent[0][:2] == bytes.fromhex("1014")
    assert sent[1][:3] == bytes.fromhex("e00505") and sent[1][12] == 0x23
    assert sent[2][:3] == bytes.fromhex("e00506") and sent[2][12] == 0x24
    assert (sent[2][4] - sent[1][4]) % 24 == 6
    assert sent[-1] == symphony.TIMER_QUERY
    await device.async_set_timer(symphony.TIMER_OFF)
    assert bytes.fromhex("e00505" + "00" * 20) in sent
    device._handle_notify(_notify(TIMERS_SLOT6_OFF, 9))
    assert device.state.timers == {6: "08:08 off daily"}


async def test_remote_music_mode_is_read_back(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    device = _device(hass)
    device._handle_notify(_notify(MUSIC_FROM_REMOTE, 1))
    assert device.state.mic is True
    assert device.state.music_mode == 6


async def test_holiday_palettes_and_white(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    device = _device(hass)
    for name in ("Christmas", "Patriotic", "Candy Cane", "Halloween", "Cool white"):
        assert name in symphony.PALETTES
    assert symphony.palette_colors("Candy Cane", (0.0, 0.0)) == [(0.0, 100.0), (0.0, 0.0)]
    assert device.supports_color_temp
    sent: list[bytes] = []

    async def _send(payload, opcode):
        sent.append(payload)
        return payload

    device._send = _send
    await device.async_set_mic(True)
    await device.async_turn_on(color_temp_kelvin=2700)
    assert sent[-1][:2] == bytes.fromhex("3ba1")
    assert device.state.mic is False
    assert device.state.color_mode == "color_temp"
    # The tree reads back hue 35 / sat 64 for 2700 K; CT mode stays.
    from homeassistant.util import color as color_util

    hue, sat = color_util.color_temperature_to_hs(2700)
    packed = (round(hue) << 7) | round(sat)
    frame = "EA810000C5082324145000" + f"{packed:04X}" + "6400000001150000000146010015"
    device._handle_notify(_notify(frame, 6))
    assert device.state.color_mode == "color_temp"
    device._handle_notify(_notify(STATIC_BLUE_248, 7))
    assert device.state.color_mode == "hs"


async def test_auto_cycles_effects(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    device = _device(hass)
    assert symphony.AUTO in device.effect_options()
    sent: list[bytes] = []

    async def _send(payload, opcode):
        sent.append(payload)
        return payload

    device._send = _send
    with patch.object(symphony, "AUTO_INTERVAL", 0.01):
        await device.async_turn_on(effect=symphony.AUTO)
        assert sent[-1][:2] == bytes.fromhex("e121") and sent[-1][4] == 1
        await asyncio.sleep(0.05)
        ids = {p[4] for p in sent if p[:2] == bytes.fromhex("e121")}
        assert len(ids) > 1
        # A real effect readback keeps Auto selected.
        device._handle_notify(_notify("EA810000C50823250250007C646400000001150000000146010015", 5))
        assert device.state.effect == symphony.AUTO
        await device.async_turn_off()
        count = len(sent)
        await asyncio.sleep(0.05)
        assert len(sent) == count


async def test_stale_upload_after_command_is_ignored(hass) -> None:
    await hass.async_add_executor_job(load_tables)
    device = _device(hass)
    sent: list[bytes] = []

    async def _send(payload, opcode):
        sent.append(payload)
        return payload

    device._send = _send
    await device.async_turn_on(effect=symphony.AUTO)
    # The tree first answers with the static state it had before the command.
    device._handle_notify(_notify(STATIC_BLUE_248, 1))
    assert device.state.effect == symphony.AUTO
    device._handle_notify(_notify("EA810000C50823250150007C646400000001150000000146010015", 2))
    assert device.state.effect == symphony.AUTO
    await device.async_turn_off()
