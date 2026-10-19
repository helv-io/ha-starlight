"""Advertisement parsing for Zengge-family broadcasts.

Home Assistant exposes manufacturer data with the company id as the dict key
and the remaining bytes as the value. A manufacturer-only advert is 27 bytes
and carries identity: ble version at byte 1, MAC at bytes 2-7, product id at
bytes 8-9. That layout matches the LEDnetWF integration.

When the advert also has 16-bit service data under ``00005axx`` / ``00005bxx``
/ ``00005cxx``, Home Assistant has already removed the UUID. The remaining
bytes are identity and the manufacturer value is state. Identity from service
data wins, which is what the controller app does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

COMPANY_HI = (0x5A, 0x5B, 0x5C)
_FAMILY_SERVICE = re.compile(r"^0000(?:5a|5b|5c)[0-9a-f]{2}-0000-1000-8000-00805f9b34fb$")
# sta, ble version, MAC, product id, firmware, led version.
_SERVICE_IDENTITY_LEN = 12


@dataclass(frozen=True)
class Advertisement:
    """Identity and the latest broadcast state for one controller."""

    product_id: int
    ble_version: int
    firmware: str
    firmware_ver: int
    led_version: int
    mac: str
    power: bool | None
    color_mode: str | None
    rgb: tuple[int, int, int] | None
    brightness_percent: int | None
    color_temp_percent: int | None
    effect_id: int | None
    company_id: int
    name: str | None = None
    rssi: int | None = None
    hs: tuple[float, float] | None = None
    manufacturer_state: bytes | None = None


def _company_ok(company_id: int) -> bool:
    return (company_id >> 8) & 0xFF in COMPANY_HI


def _firmware(ble_version: int, fw_lo: int, flag: int) -> tuple[int, str]:
    # bleVersion >= 6 stores the high firmware bits in flag >> 2.
    if ble_version >= 6:
        fw = ((flag >> 2) << 8) | fw_lo
    else:
        fw = fw_lo
    return fw, f"{fw_lo:02X}"


def _mac(data: bytes) -> str:
    return ":".join(f"{b:02X}" for b in data)


def parse_manufacturer_data(manufacturer_data: dict[int, bytes]) -> Advertisement | None:
    """Parse a bleak manufacturer_data dict. Returns None when it is not ours."""
    block = _manufacturer_block(manufacturer_data)
    if block is None:
        return None
    company_id, data = block
    if len(data) < 27:
        return None
    data = data[:27]
    ble_version = data[1]
    product_id = (data[8] << 8) | data[9]
    fw_num, fw_text = _firmware(ble_version, data[10], data[12] if len(data) > 12 else 0)
    power, color_mode, rgb, bright, temp, effect = _parse_standard_state(data, ble_version)
    return Advertisement(
        product_id=product_id,
        ble_version=ble_version,
        firmware=fw_text,
        firmware_ver=fw_num,
        led_version=data[11],
        mac=_mac(data[2:8]),
        power=power,
        color_mode=color_mode,
        rgb=rgb,
        brightness_percent=bright,
        color_temp_percent=temp,
        effect_id=effect,
        company_id=company_id,
    )


def _manufacturer_block(manufacturer_data: dict[int, bytes] | None) -> tuple[int, bytes] | None:
    if not manufacturer_data:
        return None
    for company_id, raw in manufacturer_data.items():
        if _company_ok(company_id):
            return company_id, bytes(raw)
    return None


def _parse_standard_state(
    data: bytes, ble_version: int
) -> tuple[
    bool | None,
    str | None,
    tuple[int, int, int] | None,
    int | None,
    int | None,
    int | None,
]:
    """Read power and color from the standard-light block at offset 14.

    Power is 0x23 or 0x24. RGB uses mode 0x61. Effects use 0x25 or ids 37-56.
    """
    if ble_version < 5 or len(data) < 22:
        return None, None, None, None, None, None
    power: bool | None = None
    if data[14] == 0x23:
        power = True
    elif data[14] == 0x24:
        power = False
    mode = data[15]
    sub = data[16]
    color_mode: str | None = None
    rgb = None
    bright = None
    temp = None
    effect = None
    if mode == 0x61 and sub in (0xF0, 0x01, 0x0B):
        color_mode = "rgb"
        rgb = (data[18], data[19], data[20])
    elif mode == 0x61 and sub == 0x0F:
        color_mode = "cct"
        bright = data[17] if data[17] <= 100 else None
        temp = data[21] if len(data) > 21 and data[21] <= 100 else None
    elif mode == 0x25 or 37 <= mode <= 56:
        color_mode = "effect"
        effect = sub if mode == 0x25 else mode
        if data[18] <= 100:
            bright = data[18]
    return power, color_mode, rgb, bright, temp, effect


def parse_stair_state(data: bytes) -> tuple[bool, tuple[float, float] | None] | None:
    """Parse one stair state record.

    The app reads a 0x23/0x24 flag at byte 2 and hue/saturation at bytes 8-9.
    The record is ignored unless that flag is present, so a state block with
    a different header is left unknown instead of being forced into a color.
    """
    if len(data) < 10 or data[2] not in (0x23, 0x24):
        return None
    packed = (data[8] << 8) | data[9]
    hue = (packed >> 7) & 0x1FF
    sat = packed & 0x7F
    hs = (float(hue), float(sat)) if hue <= 360 and sat <= 100 else None
    return data[2] == 0x23, hs


def _service_identity(service_data: dict[str, bytes] | None) -> Advertisement | None:
    """Identity from a family service-data value with the UUID already removed."""
    if not service_data:
        return None
    for key, value in service_data.items():
        text = str(key).lower()
        if _FAMILY_SERVICE.match(text) is None:
            continue
        data = bytes(value)
        if len(data) < _SERVICE_IDENTITY_LEN:
            continue
        ble_version = data[1]
        flag = data[12] if len(data) > 12 else 0
        fw_num, fw_text = _firmware(ble_version, data[10], flag)
        return Advertisement(
            product_id=(data[8] << 8) | data[9],
            ble_version=ble_version,
            firmware=fw_text,
            firmware_ver=fw_num,
            led_version=data[11],
            mac=_mac(data[2:8]),
            power=None,
            color_mode=None,
            rgb=None,
            brightness_percent=None,
            color_temp_percent=None,
            effect_id=None,
            company_id=int(text[4:8], 16),
        )
    return None


def _split_state(data: bytes, ble_version: int, product) -> Advertisement | None:
    """Read state from a manufacturer value that is not an identity block."""
    from .state import decode_payload

    decoded = decode_payload(data, product)
    if decoded.known:
        if decoded.hs or decoded.rgb:
            color_mode = "hs"
        elif decoded.color_temp:
            color_mode = "cct"
        else:
            color_mode = None
        return Advertisement(
            product_id=0,
            ble_version=ble_version,
            firmware="",
            firmware_ver=0,
            led_version=0,
            mac="",
            power=decoded.is_on,
            color_mode=color_mode,
            rgb=decoded.rgb,
            brightness_percent=decoded.brightness,
            color_temp_percent=None,
            effect_id=decoded.effect_id,
            company_id=0,
            hs=decoded.hs,
            manufacturer_state=data,
        )
    if product is not None and getattr(product, "kind", "") == "stair":
        return None
    power, color_mode, rgb, bright, temp, effect = _parse_standard_state(data, ble_version)
    if power is None and color_mode is None:
        return None
    return Advertisement(
        product_id=0,
        ble_version=ble_version,
        firmware="",
        firmware_ver=0,
        led_version=0,
        mac="",
        power=power,
        color_mode=color_mode,
        rgb=rgb,
        brightness_percent=bright,
        color_temp_percent=temp,
        effect_id=effect,
        company_id=0,
        manufacturer_state=data,
    )


def parse_service_info(service_info) -> Advertisement | None:
    """Parse a Home Assistant BluetoothServiceInfoBleak."""
    from .products import get_product

    manufacturer = _manufacturer_block(dict(getattr(service_info, "manufacturer_data", None) or {}))
    service = _service_identity(getattr(service_info, "service_data", None))
    if service is not None:
        product = get_product(service.product_id)
        state = None
        raw_state = None
        if manufacturer is not None:
            raw_state = manufacturer[1]
            state = _split_state(raw_state, service.ble_version, product)
        parsed = Advertisement(
            product_id=service.product_id,
            ble_version=service.ble_version,
            firmware=service.firmware,
            firmware_ver=service.firmware_ver,
            led_version=service.led_version,
            mac=service.mac,
            power=state.power if state else None,
            color_mode=state.color_mode if state else None,
            rgb=state.rgb if state else None,
            brightness_percent=state.brightness_percent if state else None,
            color_temp_percent=state.color_temp_percent if state else None,
            effect_id=state.effect_id if state else None,
            company_id=service.company_id,
            hs=state.hs if state else None,
            manufacturer_state=raw_state,
        )
    else:
        parsed = parse_manufacturer_data(
            dict(getattr(service_info, "manufacturer_data", None) or {})
        )
    if parsed is None:
        return None
    return Advertisement(
        product_id=parsed.product_id,
        ble_version=parsed.ble_version,
        firmware=parsed.firmware,
        firmware_ver=parsed.firmware_ver,
        led_version=parsed.led_version,
        mac=parsed.mac,
        power=parsed.power,
        color_mode=parsed.color_mode,
        rgb=parsed.rgb,
        brightness_percent=parsed.brightness_percent,
        color_temp_percent=parsed.color_temp_percent,
        effect_id=parsed.effect_id,
        company_id=parsed.company_id,
        name=getattr(service_info, "name", None),
        rssi=getattr(service_info, "rssi", None),
        hs=parsed.hs,
        manufacturer_state=parsed.manufacturer_state,
    )


# Alias used by the package exports and tests.
parse_advertisement = parse_service_info
