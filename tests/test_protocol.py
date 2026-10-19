"""Frame, advertisement, product, and command tests. No Bluetooth."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.starlight.protocol.advert import (
    parse_manufacturer_data,
    parse_service_info,
    parse_stair_state,
)
from custom_components.starlight.protocol.products import get_product, known_product_ids
from custom_components.starlight.protocol.rgb import (
    color_payload,
    effect_payload,
    power_payload,
    state_query_payload,
)
from custom_components.starlight.protocol.stair import (
    STAIR_MODES,
    modes_for_tab,
    pack_color,
    stair_install,
    stair_mode,
    stair_slow,
    stair_time,
)
from custom_components.starlight.protocol.state import (
    decode_payload,
    find_stair_record,
    summary_for,
)
from custom_components.starlight.protocol.transport import (
    build_frame,
    header_version_for,
    parse_frame,
    payload_from_notify,
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


def _all_products():
    return [product for pid in known_product_ids() if (product := get_product(pid)) is not None]


def _first(kind: str, predicate=None):
    for product in _all_products():
        if product.kind != kind:
            continue
        if predicate is None or predicate(product):
            return product
    raise AssertionError(f"no {kind} product matched")


def test_stair_power_uses_app_form() -> None:
    """Stair state protocols that list switch_led_v3 use the accepted power bytes."""
    product = _first("stair", lambda item: item.supports("switch_led_v3"))
    assert power_payload(product, True).hex() == "e001012300000000000000000000"
    assert power_payload(product, False).hex() == "e001012400000000000000000000"


def test_other_products_keep_v3_template() -> None:
    """The shared switch_led_v3 template stays in place for non-stair products."""
    product = _first("rgb", lambda item: item.supports("switch_led_v3"))
    payload = power_payload(product, True).hex()
    assert payload.startswith("e001")
    assert "3b23" in payload


def test_color_picks_form_for_old_firmware() -> None:
    product = _first(
        "rgb",
        lambda item: item.supports("colour_data") and item.supports("colour_data_v2"),
    )
    old = color_payload(product, 255, 0, 0, 100, ble_version=3)
    assert old[0] == 0x31
    new = color_payload(product, 255, 0, 0, 100, ble_version=8)
    assert new[0] == 0x3B
    assert new[1] == 0xA1


def test_addressable_effect() -> None:
    product = _first("addressable")
    payload = effect_payload(product, 4, 50, 80)
    assert payload is not None
    assert payload[0] == 0x42
    assert payload[1] == 4


def test_white_and_rgbw_products_exist() -> None:
    """CCT and RGBWW rows are present and keep their table kind."""
    cct = _first("cct")
    rgbww = _first("rgbww")
    assert "cct" in f"{cct.category} {cct.state}".lower() or cct.kind == "cct"
    assert rgbww.kind == "rgbww"
    assert cct.product_id != rgbww.product_id


def test_stair_helpers() -> None:
    assert stair_slow(True) == bytes((0xEF, 0x15, 0x23))
    assert stair_slow(False) == bytes((0xEF, 0x15, 0x24))
    assert stair_time(10, 20) == bytes((0xEF, 0x14, 10, 20, 0, 0, 0, 0))
    install = stair_install(32)
    assert install[:2] == bytes((0xEF, 0x11))
    assert install[3] == 0 and install[4] == 32
    assert len(STAIR_MODES) == 16
    labels = [mode.label for mode in STAIR_MODES]
    assert len(set(labels)) == len(labels)
    by_key = {mode.key: mode for mode in STAIR_MODES}
    assert by_key["full"].wire == 1 and by_key["full"].tab == "time"
    assert by_key["step"].wire == 2 and by_key["single_step"].wire == 2
    assert by_key["follow"].wire == 3 and by_key["three_follow"].wire == 3
    assert by_key["two_step"].wire == 13 and by_key["single_follow"].wire == 14
    assert {mode.tab for mode in modes_for_tab("stream")} == {"stream"}
    full = stair_mode(0, 100, False, 1, pack_color(0, 100, 100))
    assert full.hex() == "ef1000640024000101006464"
    assert stair_mode(0, 100, False, 1, opcode=0x20)[:2] == bytes((0xEF, 0x20))


def _format_b() -> bytes:
    data = bytearray(27)
    data[1] = 8
    data[2:8] = bytes.fromhex("AABBCCDDEEFF")
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
    assert advert.mac == "AA:BB:CC:DD:EE:FF"
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


def test_ffff_service_data_is_not_identity() -> None:
    """The GATT uuid is not an identity block. Family service data is."""
    service = bytearray(16)
    service[1] = 0x5A
    service[3] = 9
    service[10] = 0x02
    service[11] = 0x14
    info = SimpleNamespace(
        manufacturer_data={},
        service_data={"0000ffff-0000-1000-8000-00805f9b34fb": bytes(service)},
        name="stair",
        rssi=-42,
    )
    assert parse_service_info(info) is None


def test_split_advert_identity() -> None:
    """Service data is identity. The manufacturer value is state and must not win."""
    state = bytes.fromhex("8023030000f03c645f645f01006420000f235f0103000500640000")
    identity = bytes.fromhex("8007aabbccddeeff021415010101")
    bogus = parse_manufacturer_data({0x5A02: state})
    assert bogus is not None
    info = SimpleNamespace(
        manufacturer_data={0x5A02: state},
        service_data={"00005a02-0000-1000-8000-00805f9b34fb": identity},
        name="IOTBT65B",
        rssi=-87,
    )
    advert = parse_service_info(info)
    assert advert is not None
    assert advert.product_id == 0x0214
    assert advert.product_id != bogus.product_id
    assert advert.ble_version == 7
    assert advert.mac == "AA:BB:CC:DD:EE:FF"
    assert advert.firmware == "15"
    assert advert.led_version == 1
    assert advert.company_id == 0x5A02
    assert advert.rssi == -87
    assert advert.power is True
    assert advert.hs == (0.0, 100.0)
    assert advert.brightness_percent == 95
    assert advert.manufacturer_state == state
    assert header_version_for(advert.ble_version) == 0
    product = get_product(advert.product_id)
    assert product is not None
    assert product.kind == "stair"
    assert "stair_16_32" in product.functions
    assert product.channels == 32
    assert parse_stair_state(state) is None
    assert parse_stair_state(state[1:26]) is None
    assert find_stair_record(state) is not None
    decoded = decode_payload(state, product)
    assert decoded.is_on is True
    assert decoded.hs == (0.0, 100.0)
    assert decoded.brightness == 95
    assert decoded.induction is True
    assert decoded.slow_open is True
    assert decoded.stair_mode is None


NOTIFY_STATE = bytes.fromhex("ea810100140123000000f000646464640100")
ADVERT_STATE = bytes.fromhex("8023030000f03c645f645f01006420000f235f0103000500640000")


def test_state_query_and_response_wrapper() -> None:
    """The live query is opcode 0x0A. Opcode 0x15 returns the application bytes."""
    query = build_frame(state_query_payload(), 0, 1, 0x0A)
    assert query.hex() == "000180000004050a818a8b96"
    opcode, payload = payload_from_notify(query)
    assert opcode == 0x0A
    assert payload == state_query_payload()

    wrapped = build_frame(NOTIFY_STATE, 0, 1, 0x15)
    opcode, payload = payload_from_notify(wrapped)
    assert opcode == 0x15
    assert payload == NOTIFY_STATE

    inner = build_frame(bytes.fromhex("811d2361f000ff00000002003000"), 0, 2, 0x0C)
    outer = build_frame(inner, 0, 1, 0x15)
    opcode, payload = payload_from_notify(outer)
    assert opcode == 0x0C
    assert payload.hex() == "811d2361f000ff00000002003000"


def test_stair_notify_decodes_full_red() -> None:
    """Live 0x15 payload: power on, Full, hue 200, full saturation and brightness."""
    product = _first("stair")
    decoded = decode_payload(NOTIFY_STATE, product)
    assert decoded.is_on is True
    assert decoded.brightness == 100
    assert decoded.hs == (200.0, 100.0)
    assert decoded.stair_mode is not None
    assert decoded.stair_mode.key == "full"
    assert decoded.tab == "time"
    assert decoded.induction is False
    assert decoded.slow_open is False
    assert (
        summary_for(
            is_on=decoded.is_on,
            effect=decoded.stair_mode.label,
            brightness=decoded.brightness,
        )
        == "on, Full, 100%"
    )


def test_rgb_state_replies() -> None:
    """0x81 color and 0x25 effect replies stay on the RGB parser."""
    product = _first("rgb")
    color = decode_payload(bytes.fromhex("811d2361f000ff00000002003000"), product)
    assert color.is_on is True
    assert color.rgb == (255, 0, 0)
    assert color.stair_mode is None
    effect = decode_payload(bytes.fromhex("8100232530640000000000000000"), product)
    assert effect.is_on is True
    assert effect.effect_id == 48
    assert effect.brightness == 100
    # A stair product must not be required for this reply, and an RGB product
    # must not be parsed as a stair record.
    assert decode_payload(bytes.fromhex("8100232530640000000000000000"), product).stair_mode is None


def test_stair_command_echoes() -> None:
    product = _first("stair")
    timing = decode_payload(stair_time(12, 34), product)
    assert timing.run_time == 12
    assert timing.hold_time == 34
    slow = decode_payload(stair_slow(True), product)
    assert slow.slow_open is True
    assert decode_payload(stair_slow(False), product).slow_open is False
    echoed = decode_payload(stair_mode(0, 40, True, 2, pack_color(0, 100, 100)), product)
    assert echoed.is_on is True
    assert echoed.brightness == 40
    assert echoed.induction is True
    assert echoed.stair_mode is not None
    assert echoed.stair_mode.key == "step"
    assert echoed.tab == "step"


def test_stair_state_flag() -> None:
    record = bytearray(10)
    record[2] = 0x24
    record[8] = 0x00
    record[9] = 0x64
    assert parse_stair_state(bytes(record)) == (False, (0.0, 100.0))


def test_product_table() -> None:
    products = _all_products()
    kinds = {product.kind for product in products}
    assert {"stair", "rgb", "rgbww", "cct", "addressable"} <= kinds
    stairs = [
        product
        for product in products
        if "stair" in product.category.lower() or "stair" in product.state.lower()
    ]
    assert stairs
    assert {product.kind for product in stairs} == {"stair"}
    assert any(product.channels == 32 and "stair_16_32" in product.functions for product in stairs)
    assert any(
        product.channels == 16 and "stair_16_32" not in product.functions for product in stairs
    )
    assert get_product(999999) is None
    assert len(_first("rgb").functions) > 5
