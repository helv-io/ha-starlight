"""Advertisement parsing for the Zengge-family manufacturer block.

Home Assistant exposes manufacturer data with the company id as the dict
key and the remaining bytes as the value (27 bytes for this family).
The company id high byte is 0x5A, 0x5B, or 0x5C. The low byte is a status
byte, so the id is not a single registered company number.

Field positions for the 27-byte value match the layout used by the
LEDnetWF integration. Identity bytes also appear in 16-byte service data
when bleVersion is 7 or higher.
"""

from __future__ import annotations

from dataclasses import dataclass

COMPANY_HI = (0x5A, 0x5B, 0x5C)
SERVICE_MARK = "ffff"


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


def _company_ok(company_id: int) -> bool:
    return (company_id >> 8) & 0xFF in COMPANY_HI


def _firmware(ble_version: int, fw_lo: int, flag: int) -> tuple[int, str]:
    # bleVersion >= 6 stores the high firmware bits in flag >> 2.
    if ble_version >= 6:
        fw = ((flag >> 2) << 8) | fw_lo
    else:
        fw = fw_lo
    return fw, f"{fw_lo:02X}"


def parse_manufacturer_data(manufacturer_data: dict[int, bytes]) -> Advertisement | None:
    """Parse a bleak manufacturer_data dict. Returns None when it is not ours."""
    if not manufacturer_data:
        return None
    for company_id, raw in manufacturer_data.items():
        if not _company_ok(company_id):
            continue
        data = bytes(raw)
        if len(data) < 27:
            continue
        data = data[:27]
        ble_version = data[1]
        mac = ":".join(f"{b:02X}" for b in data[2:8])
        product_id = (data[8] << 8) | data[9]
        fw_num, fw_text = _firmware(ble_version, data[10], data[12] if len(data) > 12 else 0)
        led_version = data[11]
        power, color_mode, rgb, bright, temp, effect = _parse_state(data, ble_version)
        return Advertisement(
            product_id=product_id,
            ble_version=ble_version,
            firmware=fw_text,
            firmware_ver=fw_num,
            led_version=led_version,
            mac=mac,
            power=power,
            color_mode=color_mode,
            rgb=rgb,
            brightness_percent=bright,
            color_temp_percent=temp,
            effect_id=effect,
            company_id=company_id,
        )
    return None


def _parse_state(
    data: bytes, ble_version: int
) -> tuple[
    bool | None,
    str | None,
    tuple[int, int, int] | None,
    int | None,
    int | None,
    int | None,
]:
    """Read power and color from the 11-byte state block at offset 14.

    This is the standard-light layout. Stair broadcasts may use the same
    power byte. The stair-specific notify parser is separate and unverified.
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


def _service_data_block(service_data: dict[str, bytes] | None) -> bytes | None:
    if not service_data:
        return None
    for key, value in service_data.items():
        if SERVICE_MARK in str(key).lower() and len(value) >= 16:
            return bytes(value)
    return None


def parse_service_info(service_info) -> Advertisement | None:
    """Parse a Home Assistant BluetoothServiceInfoBleak."""
    parsed = parse_manufacturer_data(dict(service_info.manufacturer_data or {}))
    service = _service_data_block(getattr(service_info, "service_data", None))
    # bleVersion >= 7 repeats identity in service data. Prefer that product id
    # when the manufacturer block was only a state trailer. UNVERIFIED when
    # the two disagree; the service-data id wins because the app does that.
    if service is not None and service[1] in COMPANY_HI and len(service) >= 16:
        ble_version = service[3]
        product_id = (service[10] << 8) | service[11]
        mac = ":".join(f"{b:02X}" for b in service[4:10])
        fw_num, fw_text = _firmware(ble_version, service[12], service[14])
        if parsed is None or ble_version >= 7:
            base = parsed
            parsed = Advertisement(
                product_id=product_id or (base.product_id if base else 0),
                ble_version=ble_version,
                firmware=fw_text,
                firmware_ver=fw_num,
                led_version=service[13],
                mac=mac or (base.mac if base else ""),
                power=base.power if base else None,
                color_mode=base.color_mode if base else None,
                rgb=base.rgb if base else None,
                brightness_percent=base.brightness_percent if base else None,
                color_temp_percent=base.color_temp_percent if base else None,
                effect_id=base.effect_id if base else None,
                company_id=base.company_id if base else (service[1] << 8) | service[2],
            )
    if parsed is None:
        return None
    name = getattr(service_info, "name", None)
    rssi = getattr(service_info, "rssi", None)
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
        name=name,
        rssi=rssi,
    )


# Alias used by the package exports and tests.
parse_advertisement = parse_service_info
