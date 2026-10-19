"""Frame, advertisement, product, and command tests. No Bluetooth."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.starlight.protocol.advert import (
    parse_manufacturer_data,
    parse_service_info,
)
from custom_components.starlight.protocol.products import get_product
from custom_components.starlight.protocol.rgb import (
    color_payload,
    effect_payload,
    power_payload,
    state_query_payload,
)
from custom_components.starlight.protocol.stair import (
    pack_color,
    stair_install,
    stair_mode,
    stair_slow,
    stair_time,
)
from custom_components.starlight.protocol.transport import (
    build_frame,
    header_version_for,
    parse_frame,
)


def _stair_color() -> bytes:
    return stair_mode(0, 50, False, 2, pack_color(0, 0, 100))


def test_frame_golden_bytes() -> None:
    """Match the frames recorded from the app's transport encoder."""
    payload = _stair_color()
    assert payload.hex() == "ef1000320024000102000064"
    assert build_frame(payload, 0, 1, 0x0A).hex() == "00018000000c0d0aef1000320024000102000064"
    assert build_frame(payload, 1, 2, 0x0A).hex() == "01028000000c000d0aef1000320024000102000064"


def test_frame_roundtrip() -> None:
    payload = _stair_color()
    for version, seq in ((0, 1), (1, 9)):
        raw = build_frame(payload, version, seq, 0x0A)
        frame = parse_frame(raw)
        assert frame is not None
        assert frame.version == version
        assert frame.seq == seq
        assert frame.opcode == 0x0A
        assert frame.payload == payload
        assert frame.segmented is False


def test_header_version() -> None:
    assert header_version_for(7) == 0
    assert header_version_for(8) == 1
    assert header_version_for(None) == 0


def test_legacy_power_checksum() -> None:
    assert power_payload(None, True).hex() == "71230fa3"
    assert power_payload(None, False).hex() == "71240fa4"
    assert state_query_payload().hex() == "818a8b96"


def test_stair_power_uses_v3_template() -> None:
    """The stair products list switch_led_v3, so power uses that template."""
    assert power_payload(get_product(532), True).hex() == "e001003b2300000000000000000000"


def test_color_picks_form_for_old_firmware() -> None:
    product = get_product(8)
    assert product is not None and product.kind == "rgb"
    old = color_payload(product, 255, 0, 0, 100, ble_version=3)
    assert old[0] == 0x31
    new = color_payload(product, 255, 0, 0, 100, ble_version=8)
    assert new[0] == 0x3B
    assert new[1] == 0xA1


def test_addressable_effect() -> None:
    product = get_product(170)
    assert product is not None and product.kind == "addressable"
    payload = effect_payload(product, 4, 50, 80)
    assert payload is not None
    assert payload[0] == 0x42
    assert payload[1] == 4


def test_stair_helpers() -> None:
    assert stair_slow(True) == bytes((0xEF, 0x15, 0x23))
    assert stair_slow(False) == bytes((0xEF, 0x15, 0x24))
    assert stair_time(10, 20) == bytes((0xEF, 0x14, 10, 20, 0, 0, 0, 0))
    install = stair_install(32)
    assert install[:2] == bytes((0xEF, 0x11))
    assert install[3] == 0 and install[4] == 32


def _format_b() -> bytes:
    data = bytearray(27)
    data[1] = 8
    data[2:8] = bytes.fromhex("0865F01CE65B")
    data[8] = 0x02
    data[9] = 0x14
    data[10] = 0x0C
    data[14] = 0x23
    data[15] = 0x61
    data[16] = 0xF0
    data[18:21] = bytes((255, 0, 0))
    return bytes(data)


def test_advert_format_b() -> None:
    advert = parse_manufacturer_data({0x5A01: _format_b()})
    assert advert is not None
    assert advert.product_id == 0x0214
    assert advert.ble_version == 8
    assert advert.mac == "08:65:F0:1C:E6:5B"
    assert advert.firmware == "0C"
    assert advert.power is True
    assert advert.color_mode == "rgb"
    assert advert.rgb == (255, 0, 0)
    assert header_version_for(advert.ble_version) == 1


def test_advert_accepts_5b_and_rejects_noise() -> None:
    assert parse_manufacturer_data({0x5B10: _format_b()}) is not None
    assert parse_manufacturer_data({0x5C00: _format_b()}) is not None
    assert parse_manufacturer_data({0x004C: _format_b()}) is None
    assert parse_manufacturer_data({0x5A01: b"\x00" * 10}) is None
    assert parse_manufacturer_data({}) is None


def test_service_data_identity() -> None:
    service = bytearray(16)
    service[1] = 0x5A
    service[3] = 9
    service[4:10] = bytes.fromhex("0865F01CE65B")
    service[10] = 0x00
    service[11] = 0xC6
    service[12] = 0x04
    info = SimpleNamespace(
        manufacturer_data={},
        service_data={"0000ffff-0000-1000-8000-00805f9b34fb": bytes(service)},
        name="stair",
        rssi=-42,
    )
    advert = parse_service_info(info)
    assert advert is not None
    assert advert.product_id == 198
    assert advert.ble_version == 9
    assert advert.rssi == -42


def test_product_table() -> None:
    stair16 = get_product(198)
    stair32 = get_product(532)
    assert stair16 is not None and stair16.kind == "stair" and stair16.channels == 16
    assert stair32 is not None and stair32.kind == "stair" and stair32.channels == 32
    assert "stair_16_32" in stair32.functions
    assert get_product(8) is not None
    assert get_product(999999) is None
    assert len(get_product(8).functions) > 5
