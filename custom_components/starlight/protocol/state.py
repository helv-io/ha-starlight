"""Decode notification payloads and advertisement state blocks.

The transport header is removed first. Opcode 0x15 is the response wrapper
used by the live controllers: its payload is the application record, usually
an ``EA 81`` status upload. Which parser runs depends on the product's state
protocol. Stair products use the app's stair state layout. Other products use
the 0x81 query reply, including mode 0x25 effects.
"""

from __future__ import annotations

from dataclasses import dataclass

from .products import Product
from .rgb import parse_state_response
from .stair import TAB_LABELS, StairMode, mode_by_wire, tab_by_index

# parseWifiBleV2StairLightData reads a 0x23/0x24 flag at byte 2. The header
# in front of that record is not fixed, so the record is located by the flag.
_STAIR_POWER = (0x23, 0x24)


@dataclass
class DecodedState:
    """Fields recovered from one notification or advertisement."""

    is_on: bool | None = None
    brightness: int | None = None
    hs: tuple[float, float] | None = None
    rgb: tuple[int, int, int] | None = None
    effect_id: int | None = None
    stair_mode: StairMode | None = None
    tab: str | None = None
    induction: bool | None = None
    slow_open: bool | None = None
    run_time: int | None = None
    hold_time: int | None = None
    color_temp: bool = False

    @property
    def known(self) -> bool:
        """True when at least one light field was recovered."""
        return any(
            value is not None
            for value in (
                self.is_on,
                self.brightness,
                self.hs,
                self.rgb,
                self.effect_id,
                self.stair_mode,
                self.induction,
                self.slow_open,
                self.run_time,
                self.hold_time,
            )
        )


def summary_for(
    *,
    is_on: bool | None,
    effect: str | None,
    brightness: int | None,
) -> str:
    """Short text for the last-notification sensor."""
    parts: list[str] = []
    if is_on is True:
        parts.append("on")
    elif is_on is False:
        parts.append("off")
    if effect:
        parts.append(effect)
    if brightness is not None:
        parts.append(f"{brightness}%")
    return ", ".join(parts)


def is_stair_protocol(product: Product | None) -> bool:
    """True when the product's state protocol or category is a stair light."""
    if product is None:
        return False
    names = (product.category, product.state, *product.states)
    return any("stair" in name.lower() for name in names)


def decode_payload(data: bytes, product: Product | None) -> DecodedState:
    """Decode one application payload for this product."""
    if not data:
        return DecodedState()
    if data[0] == 0xEF:
        echoed = _decode_ef(data)
        if echoed.known:
            return echoed
    if is_stair_protocol(product):
        window = find_stair_record(data)
        if window is not None:
            return _decode_stair_window(window)
    rgb = _decode_rgb(data)
    if rgb.known:
        return rgb
    return DecodedState()


def find_stair_record(data: bytes) -> bytes | None:
    """Return the stair state record, or None when the power flag is absent.

    The app reads byte 2 as 0x23 or 0x24 and bytes 8-9 as hue and saturation.
    The bytes in front of that record vary, so each alignment is tried.
    """
    if len(data) < 10:
        return None
    for start in range(0, len(data) - 9):
        window = data[start:]
        if window[2] not in _STAIR_POWER:
            continue
        hue, sat = _hue_sat(window)
        if hue <= 360 and sat <= 100:
            return window
    return None


def _hue_sat(window: bytes) -> tuple[int, int]:
    packed = (window[8] << 8) | window[9]
    return (packed >> 7) & 0x1FF, packed & 0x7F


def _decode_stair_window(window: bytes) -> DecodedState:
    """Apply parseWifiBleV2StairLightData and the neighbouring field guesses.

    Byte 2 is power. Byte 3 is a small integer from the app. Byte 4 is a
    nonzero flag and byte 5 carries the 1/2/3 bit flags. Bytes 8-9 are hue
    and saturation. The byte after that is treated as the color value when
    it is 1-100, which matches the color record the app sends. Otherwise
    byte 3 is the brightness when it is in that range. The byte before the
    power flag is the mode when it is one of the stair wire values.
    """
    decoded = DecodedState(is_on=window[2] == 0x23)
    hue, sat = _hue_sat(window)
    if hue <= 360 and sat <= 100:
        decoded.hs = (float(hue), float(sat))
    if len(window) > 10 and 1 <= window[10] <= 100:
        decoded.brightness = window[10]
    elif 1 <= window[3] <= 100:
        decoded.brightness = window[3]
    decoded.induction = window[4] != 0 or bool(window[5] & 0x01)
    decoded.slow_open = bool(window[5] & 0x02)
    mode = mode_by_wire(window[1])
    if mode is not None:
        decoded.stair_mode = mode
        decoded.tab = mode.tab
    elif (tab := tab_by_index(window[3])) is not None and decoded.brightness != window[3]:
        decoded.tab = tab
    return decoded


def _decode_rgb(data: bytes) -> DecodedState:
    """Decode a 0x81 state reply, including an 0x25 effect mode."""
    packet = _find_status_packet(data)
    if packet is None:
        return DecodedState()
    parsed = parse_state_response(packet)
    if parsed is None:
        return DecodedState()
    decoded = DecodedState(is_on=bool(parsed["is_on"]))
    if parsed["is_rgb"]:
        decoded.rgb = (parsed["r"], parsed["g"], parsed["b"])
    elif parsed["is_white"]:
        decoded.color_temp = True
        level = parsed["value1"]
        if 0 <= level <= 100:
            decoded.brightness = level
    elif parsed["is_effect"] and parsed["effect_id"] is not None:
        decoded.effect_id = int(parsed["effect_id"])
        level = parsed["value1"]
        if 1 <= level <= 100:
            decoded.brightness = level
    return decoded


def _find_status_packet(data: bytes) -> bytes | None:
    """Find a 14-byte 0x81 record, including one nested after EA 81."""
    if len(data) >= 14 and data[0] == 0x81:
        return data
    limit = len(data) - 13
    for start in range(1, max(0, limit)):
        if data[start] == 0x81 and data[start + 2] in _STAIR_POWER:
            return data[start:]
    return None


def _decode_ef(data: bytes) -> DecodedState:
    """Decode an echoed stair command. EF 10, EF 14, and EF 15 are handled."""
    decoded = DecodedState()
    if len(data) < 3 or data[0] != 0xEF:
        return decoded
    opcode = data[1]
    if opcode in (0x10, 0x20) and len(data) >= 9:
        tab = tab_by_index(data[2])
        if tab is not None:
            decoded.tab = tab
        if data[3] <= 100:
            decoded.brightness = data[3]
        if data[5] in _STAIR_POWER:
            decoded.induction = data[5] == 0x23
        mode = mode_by_wire(data[8])
        if mode is not None:
            decoded.stair_mode = mode
            decoded.tab = mode.tab
        colors = data[9:]
        if len(colors) >= 2:
            packed = (colors[0] << 8) | colors[1]
            hue = (packed >> 7) & 0x1FF
            sat = packed & 0x7F
            if hue <= 360 and sat <= 100:
                decoded.hs = (float(hue), float(sat))
        decoded.is_on = True
        return decoded
    if opcode == 0x14 and len(data) >= 4:
        decoded.run_time = data[2]
        decoded.hold_time = data[3]
        return decoded
    if opcode == 0x15 and data[2] in _STAIR_POWER:
        decoded.slow_open = data[2] == 0x23
        return decoded
    return decoded


def field_map(decoded: DecodedState, *, effect: str | None, raw: str, opcode: int | None) -> dict:
    """Flat attributes for the sensor and diagnostics."""
    fields: dict = {"raw": raw}
    if opcode is not None:
        fields["opcode"] = f"0x{opcode:02X}"
    if decoded.is_on is not None:
        fields["power"] = "on" if decoded.is_on else "off"
    if decoded.brightness is not None:
        fields["brightness"] = decoded.brightness
    if effect:
        fields["effect"] = effect
    if decoded.tab:
        fields["tab"] = TAB_LABELS.get(decoded.tab, decoded.tab)
    if decoded.hs is not None:
        fields["hue"] = round(decoded.hs[0])
        fields["saturation"] = round(decoded.hs[1])
    if decoded.rgb is not None:
        fields["rgb"] = list(decoded.rgb)
    if decoded.effect_id is not None:
        fields["effect_id"] = decoded.effect_id
    if decoded.induction is not None:
        fields["motion"] = decoded.induction
    if decoded.slow_open is not None:
        fields["soft_start"] = decoded.slow_open
    if decoded.run_time is not None:
        fields["run_time"] = decoded.run_time
    if decoded.hold_time is not None:
        fields["hold_time"] = decoded.hold_time
    return fields


__all__ = [
    "DecodedState",
    "decode_payload",
    "field_map",
    "find_stair_record",
    "is_stair_protocol",
    "summary_for",
]
