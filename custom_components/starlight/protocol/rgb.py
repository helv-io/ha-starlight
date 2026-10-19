"""RGB, white, effect, and music payloads.

The byte layouts are the ones the LEDnetWF integration has been sending to
real controllers. Checksums and the 0x31, 0x3B, 0x38, 0x42, 0x61, and 0x73
opcodes are from that work. Which product receives which layout is chosen
from the product table and is still an assumption for ids nobody has captured.
"""

from __future__ import annotations

import colorsys

from .commands import CommandError, build_from_template
from .products import Product, command_form

MIN_KELVIN = 2700
MAX_KELVIN = 6500


def checksum(payload: bytes) -> bytes:
    """Append the low byte of the sum."""
    return payload + bytes((sum(payload) & 0xFF,))


def ha_hs_to_rgb(hue: float, saturation: float) -> tuple[int, int, int]:
    """Convert a Home Assistant HS color at full value to RGB."""
    red, green, blue = colorsys.hsv_to_rgb(hue / 360.0, saturation / 100.0, 1.0)
    return int(red * 255), int(green * 255), int(blue * 255)


def rgb_to_hs(red: int, green: int, blue: int) -> tuple[float, float]:
    """Convert RGB bytes to Home Assistant hue and saturation."""
    hue, sat, _value = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
    return hue * 360.0, sat * 100.0


def brightness_to_percent(brightness: int) -> int:
    """Map a Home Assistant 0-255 brightness to 1-100."""
    if brightness <= 0:
        return 0
    return max(1, min(100, round(brightness * 100 / 255)))


def percent_to_brightness(percent: int) -> int:
    """Map a 0-100 level to Home Assistant brightness."""
    return max(0, min(255, round(percent * 255 / 100)))


def kelvin_to_percent(kelvin: int) -> int:
    """Map 2700-6500 K to 0-100. 0 is warm and 100 is cool. Polarity is ported."""
    kelvin = max(MIN_KELVIN, min(MAX_KELVIN, kelvin))
    return round((kelvin - MIN_KELVIN) * 100 / (MAX_KELVIN - MIN_KELVIN))


def percent_to_kelvin(percent: int) -> int:
    """Invert kelvin_to_percent."""
    percent = max(0, min(100, percent))
    return MIN_KELVIN + round(percent * (MAX_KELVIN - MIN_KELVIN) / 100)


def kelvin_to_channels(kelvin: int, level: int = 255) -> tuple[int, int]:
    """Split a color temperature into warm and cool bytes."""
    cool = kelvin_to_percent(kelvin) / 100.0
    warm = 1.0 - cool
    return int(warm * level), int(cool * level)


def speed_to_inverted_31(speed: int) -> int:
    """Map 0-100 (100 is fast) to 1-31 (1 is fast)."""
    speed = max(0, min(100, speed))
    return max(1, min(31, 1 + (30 * (100 - speed)) // 100))


def _uses_v2(product: Product | None, ble_version: int | None) -> bool:
    if product is None:
        return bool(ble_version is not None and ble_version >= 5)
    if product.kind == "addressable":
        return True
    if (
        ble_version is not None
        and ble_version < 5
        and product.best(0, ["colour_data", "switch_led"])
    ):
        return False
    return bool(
        product.supports("colour_data_v2")
        or product.supports("switch_led_v2")
        or (ble_version or 0) >= 5
    )


def power_payload(product: Product | None, on: bool, firmware: int = 0) -> bytes:
    """Build a power payload. Prefers v3, then v2, then the 0x71 command."""
    code = None
    if product is not None:
        code = product.best(firmware, ["switch_led_v3", "switch_led_v2", "switch_led"])
    form = command_form(product, code) if code else None
    if form is None:
        form = command_form(product, "switch_led")
    if form is None:
        return checksum(bytes((0x71, 0x23 if on else 0x24, 0x0F)))
    try:
        return build_from_template(
            form.cmd,
            {"open": 0x23 if on else 0x24, "preview": 0, "delay": 0, "gradient": 0},
            form.checksum,
        )
    except CommandError:
        return checksum(bytes((0x71, 0x23 if on else 0x24, 0x0F)))


def _color_3b(red: int, green: int, blue: int, brightness: int) -> bytes:
    hue, sat, _value = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
    packed = (int(hue * 360) << 7) | int(sat * 100)
    return checksum(
        bytes(
            (
                0x3B,
                0xA1,
                (packed >> 8) & 0xFF,
                packed & 0xFF,
                max(0, min(100, brightness)),
                0x00,
                0x00,
                red & 0xFF,
                green & 0xFF,
                blue & 0xFF,
                0x00,
                0x00,
            )
        )
    )


def _color_v2(red: int, green: int, blue: int, brightness: int) -> bytes:
    """Unified 0x3B color. Bytes 7-9 are a delay, not a second copy of RGB."""
    hue, sat, _value = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
    packed = (int(hue * 360) << 7) | int(sat * 100)
    return checksum(
        bytes(
            (
                0x3B,
                0xA1,
                (packed >> 8) & 0xFF,
                packed & 0xFF,
                max(0, min(100, brightness)),
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
            )
        )
    )


def _color_31(
    red: int, green: int, blue: int, warm: int = 0, cool: int = 0, *, persist: bool = False
) -> bytes:
    has_rgb = red or green or blue
    has_white = warm or cool
    if has_rgb and has_white:
        mode = 0x5A
    elif has_white:
        mode = 0x0F
    else:
        mode = 0xF0
    return checksum(
        bytes(
            (
                0x31,
                red & 0xFF,
                green & 0xFF,
                blue & 0xFF,
                warm & 0xFF,
                cool & 0xFF,
                mode,
                0xF0 if persist else 0x0F,
            )
        )
    )


def color_payload(
    product: Product | None,
    red: int,
    green: int,
    blue: int,
    brightness_pct: int,
    *,
    ble_version: int | None = None,
    persist: bool = False,
) -> bytes:
    """Build a static color payload for this product."""
    if product is not None and product.kind == "addressable":
        return _color_3b(red, green, blue, brightness_pct)
    form = command_form(product, "colour_data") if product else None
    use_form = form is not None and not _uses_v2(product, ble_version)
    if (
        product is not None
        and product.supports("colour_data_v2")
        and _uses_v2(product, ble_version)
    ):
        return _color_v2(red, green, blue, brightness_pct)
    if use_form and form is not None:
        scale = max(0, min(100, brightness_pct)) / 100
        return build_from_template(
            form.cmd,
            {
                "r": int(red * scale),
                "g": int(green * scale),
                "b": int(blue * scale),
            },
            form.checksum,
        )
    if _uses_v2(product, ble_version):
        return _color_3b(red, green, blue, brightness_pct)
    scale = max(0, min(100, brightness_pct)) / 100
    return _color_31(int(red * scale), int(green * scale), int(blue * scale), persist=persist)


def white_payload(
    product: Product | None,
    kelvin: int,
    brightness_pct: int,
    *,
    ble_version: int | None = None,
    persist: bool = False,
) -> bytes:
    """Build a white or color-temperature payload."""
    form = None
    if product is not None:
        code = product.best(0, ["temp_value_v2", "temp_value", "warm_value"])
        form = command_form(product, code) if code else None
    if form is not None and "{cct}" in form.cmd:
        # UNVERIFIED polarity: 0 is warm in the 0x3B CCT template used here.
        warm_pct = 100 - kelvin_to_percent(kelvin)
        return build_from_template(
            form.cmd,
            {"cct": warm_pct, "bright": brightness_pct, "value": brightness_pct},
            form.checksum,
        )
    if form is not None and ("{warm}" in form.cmd or "{cool}" in form.cmd or "{value}" in form.cmd):
        warm, cool = kelvin_to_channels(kelvin, 255)
        return build_from_template(
            form.cmd,
            {"warm": warm, "cool": cool, "value": warm or brightness_pct},
            form.checksum,
        )
    if _uses_v2(product, ble_version):
        warm_pct = 100 - kelvin_to_percent(kelvin)
        return checksum(
            bytes(
                (
                    0x3B,
                    0xB1,
                    0x00,
                    0x00,
                    0x00,
                    warm_pct & 0xFF,
                    max(0, min(100, brightness_pct)),
                    0x00,
                    0x00,
                    0x00,
                    0x00,
                    0x00,
                )
            )
        )
    warm, cool = kelvin_to_channels(kelvin, int(255 * brightness_pct / 100))
    return _color_31(0, 0, 0, warm, cool, persist=persist)


def effect_payload(
    product: Product | None,
    effect_id: int,
    speed: int,
    brightness_pct: int,
) -> bytes | None:
    """Build an effect payload. Returns None when this product has no effects."""
    if product is not None and product.kind == "addressable":
        return checksum(
            bytes(
                (
                    0x42,
                    effect_id & 0xFF,
                    max(0, min(100, speed)),
                    max(1, min(100, brightness_pct)),
                )
            )
        )
    code = product.best(0, ["scene_data_v2", "scene_data"]) if product else "scene_data_v2"
    if code == "scene_data_v2" or code is None:
        form = command_form(product, "scene_data_v2")
        if form is not None:
            return build_from_template(
                form.cmd,
                {
                    "model": effect_id,
                    "speed": speed_to_inverted_31(speed),
                    "bright": max(1, min(100, brightness_pct)),
                    "preview": 0,
                },
                form.checksum,
            )
    form = command_form(product, "scene_data")
    if form is not None:
        return build_from_template(
            form.cmd,
            {"model": effect_id, "speed": speed_to_inverted_31(speed)},
            form.checksum,
        )
    return checksum(bytes((0x61, effect_id & 0xFF, speed_to_inverted_31(speed), 0x0F)))


def music_payload(
    product: Product | None,
    enabled: bool,
    sensitivity: int,
    red: int = 255,
    green: int = 0,
    blue: int = 0,
    brightness_pct: int = 100,
) -> bytes:
    """Build a microphone command. Addressable lights get the long 0x73 form."""
    sensitivity = max(1, min(100, sensitivity))
    if product is not None and product.kind == "addressable":
        return checksum(
            bytes(
                (
                    0x73,
                    0x01 if enabled else 0x00,
                    0x27,
                    0x01,
                    red & 0xFF,
                    green & 0xFF,
                    blue & 0xFF,
                    0x00,
                    0x00,
                    0x00,
                    sensitivity,
                    max(1, min(100, brightness_pct)),
                )
            )
        )
    return checksum(bytes((0x73, 0x01 if enabled else 0x00, sensitivity, 0x0F)))


def state_query_payload() -> bytes:
    """Classic state query. The reply starts with 0x81."""
    return checksum(bytes((0x81, 0x8A, 0x8B)))


def parse_state_response(data: bytes) -> dict | None:
    """Parse a 14-byte 0x81 state reply.

    Layout ported from the LEDnetWF parser. Simple-effect ids 37-56 collide
    with the 0x25 effect marker, so an effect id in that range is only trusted
    when the mode byte itself is that id and the following byte is not a color flag.
    """
    if len(data) < 14 or data[0] != 0x81:
        return None
    mode = data[3]
    sub = data[4]
    is_effect = mode == 0x25 or (37 <= mode <= 56 and sub not in (0xF0, 0x0F, 0x01, 0x0B))
    is_rgb = mode == 0x61 and sub in (0xF0, 0x01, 0x0B)
    is_white = mode == 0x61 and sub == 0x0F
    if is_effect and 37 <= mode <= 56 and mode != 0x25:
        effect_id = mode
    elif is_effect:
        effect_id = sub
    else:
        effect_id = None
    return {
        "is_on": data[2] == 0x23,
        "mode": mode,
        "sub": sub,
        "is_rgb": is_rgb,
        "is_white": is_white,
        "is_effect": is_effect,
        "effect_id": effect_id,
        "value1": data[5],
        "r": data[6],
        "g": data[7],
        "b": data[8],
        "ww": data[9],
        "cw": data[11],
    }


# Named effects for ordinary RGB controllers. Ids are the 0x61 / scene_data set.
SIMPLE_EFFECTS: dict[int, str] = {
    37: "Crossfade",
    38: "Red fade",
    39: "Green fade",
    40: "Blue fade",
    41: "Yellow fade",
    42: "Cyan fade",
    43: "Purple fade",
    44: "White fade",
    45: "Red green",
    46: "Red blue",
    47: "Green blue",
    48: "Strobe",
    49: "Red strobe",
    50: "Green strobe",
    51: "Blue strobe",
    52: "Yellow strobe",
    53: "Cyan strobe",
    54: "Purple strobe",
    55: "White strobe",
    56: "Jump",
}

ADDRESSABLE_EFFECTS: dict[int, str] = {index: f"Scene {index}" for index in range(1, 21)}
SOLID = "Solid"
MICROPHONE = "Microphone"
