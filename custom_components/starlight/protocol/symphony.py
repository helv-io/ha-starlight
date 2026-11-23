"""Carrier-wave symphony lights (the app's ``hc`` categories).

These controllers drive addressable strings such as pre-lit Christmas trees.
The command families below come from the controller app's
``voice_control_ii`` builder and were checked against a live tree, where the
``EA 81`` state upload echoes the mode, effect id, and speed that were sent:

* ``E1 21``: whole-string effect (the app's custom mode).
* ``EC 03``: music mode using the controller's microphone.
* ``3B 23`` / ``3B 24``: power. These lights ignore the ``E0 01`` wrapper.
* ``3B A1``: static color (shared with other addressable lights).

Effect and music names are the English strings the app shows.
"""

from __future__ import annotations

from dataclasses import dataclass

from .products import Product

STATE_HEAD = b"\xea\x81"
STATE_MIN_LEN = 14

MODE_STATIC = 0x24
MODE_EFFECT = 0x25
MODE_MUSIC = 0x62

POWER_ON = 0x23

# Functions that only the hc-category symphony controllers list.
_SYMPHONY_FUNCTIONS = frozenset(
    {"symphony_scene_hc3", "music_data_hc3", "custom_data_hc3", "smear_hc3"}
)

# Effect ids from the app's BizSymphonySceneBean mode options.
EFFECTS: dict[int, str] = {
    1: "Wave",
    2: "Meteor",
    3: "Streamer",
    4: "Building Blocks",
    5: "Flowing Water",
    6: "Chase",
    7: "Horse Racing",
    8: "Cycle",
    9: "Breathe",
    10: "Jump",
    11: "Strobe",
    12: "Twinkling Stars",
    13: "Stars Wink",
    14: "Warning",
    15: "Collision",
    16: "Fireworks",
    17: "Comet",
    18: "Gradient Meteor",
    19: "Volcano",
    20: "Superluminal",
    21: "Rainbow Bridge",
    22: "Gradient Overlay",
    101: "Static Gradient",
    102: "Static Fill",
}

MUSIC_MODES: dict[int, str] = {
    1: "Synchronized",
    2: "Asynchronous",
    3: "Gradient",
    4: "Jump",
    5: "Strobe",
    6: "Background Flash",
}

CURRENT_COLOR = "Current color"
# Hue in degrees and saturation in percent.
PALETTES: dict[str, tuple[tuple[int, int], ...]] = {
    "Christmas": ((0, 100), (120, 100), (40, 100), (0, 0)),
    "Rainbow": ((0, 100), (30, 100), (60, 100), (120, 100), (180, 100), (240, 100), (285, 100)),
    "Warm white": ((35, 45),),
    "Red and white": ((0, 100), (0, 0)),
    "Red and green": ((0, 100), (120, 100)),
    "Blue and white": ((225, 100), (0, 0)),
    "Gold": ((40, 100), (30, 90)),
    # Holiday themes from the tree's IR remote. The app ships no fixed colors
    # for these, so they follow the remote's button art.
    "Patriotic": ((0, 100), (0, 0), (225, 100)),
    "Candy Cane": ((0, 100), (0, 0)),
    "Halloween": ((25, 100), (270, 100)),
    "Cool white": ((210, 8),),
    CURRENT_COLOR: (),
}
DEFAULT_PALETTE = "Christmas"
DEFAULT_MUSIC_MODE = 1

DIRECTION_FORWARD = 0x01
DEFAULT_DENSITY = 50


# Remote-style "AUTO": the driver walks the moving effects in turn.
AUTO = "Auto"
AUTO_INTERVAL = 30
AUTO_EFFECTS: tuple[int, ...] = tuple(i for i in EFFECTS if i < 100)

# Hardware timers. The app's get_timer_list_v2 is ``E0 06`` and the controller
# holds six slots. The driver owns slots 5 and 6 so app timers in 1-4 survive.
TIMER_QUERY = b"\xe0\x06"
TIMER_SLOT_ON = 5
TIMER_SLOT_OFF = 6
REPEAT_ONCE = 0x00
REPEAT_DAILY = 0xFE
TIMER_OFF = "Off"
TIMER_6H = "Off in 6 hours"
TIMER_8H = "Off in 8 hours"
TIMER_DAILY = "6 hours on, 18 off, daily"
TIMER_OPTIONS: tuple[str, ...] = (TIMER_OFF, TIMER_6H, TIMER_8H, TIMER_DAILY)
_ACTION_ON = 0x23
_ACTION_OFF = 0x24


def set_time_payload(when) -> bytes:
    """App ``set_time``: ``10 14 YY MM DD hh mm ss WD 00`` plus checksum."""
    body = bytes(
        (
            0x10,
            0x14,
            when.year % 100,
            when.month,
            when.day,
            when.hour,
            when.minute,
            when.second,
            when.isoweekday(),
            0x00,
        )
    )
    return body + bytes((sum(body) & 0xFF,))


def timer_slot_payload(slot: int, hour: int, minute: int, repeat: int, on: bool) -> bytes:
    """``E0 05 SS`` and a 20-byte record that runs a power command.

    Record: ``F0 hh mm 00 RP 0E E0 01 00 AC`` then zeros, where AC is 23 for
    on and 24 for off. A live tree stored it, echoed it in ``E0 06`` and
    switched off at the set minute.
    """
    record = bytearray(20)
    record[0] = 0xF0
    record[1] = hour % 24
    record[2] = minute % 60
    record[4] = repeat & 0xFF
    record[5:10] = bytes((0x0E, 0xE0, 0x01, 0x00, _ACTION_ON if on else _ACTION_OFF))
    return bytes((0xE0, 0x05, slot)) + bytes(record)


def clear_slot_payload(slot: int) -> bytes:
    """An all-zero record empties the slot."""
    return bytes((0xE0, 0x05, slot)) + bytes(20)


@dataclass(frozen=True)
class TimerSlot:
    """One stored hardware timer."""

    slot: int
    hour: int
    minute: int
    repeat: int
    on: bool


def parse_timers(data: bytes) -> dict[int, TimerSlot] | None:
    """Parse an ``E0 06`` reply. Empty slots are 7 bytes, set ones 21."""
    index = data.find(TIMER_QUERY)
    if index < 0:
        return None
    body = data[index + 2 :]
    slots: dict[int, TimerSlot] = {}
    pos = 0
    while pos < len(body):
        slot = body[pos]
        if not 1 <= slot <= 6:
            break
        if pos + 1 < len(body) and body[pos + 1] == 0xF0 and pos + 21 <= len(body):
            rec = body[pos + 1 : pos + 21]
            slots[slot] = TimerSlot(slot, rec[1], rec[2], rec[4], rec[9] == _ACTION_ON)
            pos += 21
        else:
            pos += 7
    return slots


def timer_option(slots: dict[int, TimerSlot], remembered: str) -> str:
    """Which timer choice the driver's slots describe."""
    on = slots.get(TIMER_SLOT_ON)
    off = slots.get(TIMER_SLOT_OFF)
    if off is None:
        return TIMER_OFF
    if on is not None and on.repeat == REPEAT_DAILY and off.repeat == REPEAT_DAILY:
        return TIMER_DAILY
    if remembered in (TIMER_6H, TIMER_8H):
        return remembered
    return TIMER_6H


def is_symphony(product: Product | None) -> bool:
    """True for the hc-category controllers that speak E1 21 and EC 03."""
    if product is None:
        return False
    return product.category.startswith("hc") and bool(product.functions & _SYMPHONY_FUNCTIONS)


def _pct(value: int) -> int:
    return max(0, min(100, int(value)))


def color_record(hue: float, saturation: float, value: int = 100) -> bytes:
    """Five-byte color: hue halved, saturation %, value %, two zero bytes."""
    half = int(round(hue / 2)) % 180
    return bytes((half, _pct(round(saturation)), _pct(value), 0x00, 0x00))


def palette_colors(name: str, current: tuple[float, float]) -> list[tuple[float, float]]:
    """Colors for a palette name. Unknown names and the current color use the light's color."""
    colors = PALETTES.get(name) or ()
    if not colors:
        return [current]
    return [(float(h), float(s)) for h, s in colors]


def _records(colors: list[tuple[float, float]]) -> bytes:
    colors = colors[:8] or [(0.0, 0.0)]
    out = bytearray((len(colors),))
    for hue, sat in colors:
        out += color_record(hue, sat)
    return bytes(out)


def effect_payload(
    effect_id: int,
    speed: int,
    brightness_pct: int,
    colors: list[tuple[float, float]],
    *,
    density: int = DEFAULT_DENSITY,
    direction: int = DIRECTION_FORWARD,
) -> bytes:
    """``E1 21`` custom mode.

    ``e1 21 PV BR ID OP DR DN SP 00 00 00 00 00 00 N [H/2 S V 00 00] x N``
    PV preview (0 applies), BR brightness, ID effect, OP variant, DR
    direction, DN density, SP speed.
    """
    head = bytes(
        (
            0xE1,
            0x21,
            0x00,
            max(1, _pct(brightness_pct)),
            effect_id & 0xFF,
            0x00,
            direction & 0xFF,
            _pct(density),
            max(1, _pct(speed)),
        )
    )
    return head + bytes(6) + _records(colors)


def music_payload(
    mode: int,
    sensitivity: int,
    brightness_pct: int,
    colors: list[tuple[float, float]],
) -> bytes:
    """``EC 03`` music mode with the controller's own microphone.

    ``ec 03 01 BR MD 00 SN N [H/2 S V 00 00] x N``
    """
    head = bytes(
        (
            0xEC,
            0x03,
            0x01,
            max(1, _pct(brightness_pct)),
            mode & 0xFF,
            0x00,
            max(1, _pct(sensitivity)),
        )
    )
    return head + _records(colors)


@dataclass(frozen=True)
class SymphonyState:
    """One ``EA 81`` upload."""

    is_on: bool
    mode: int
    effect_id: int
    speed: int
    hue: float
    saturation: float
    value: int


def find_state(data: bytes) -> SymphonyState | None:
    """Parse an ``EA 81`` upload.

    Power at 6, mode 7, effect 8, speed 9. Bytes 11-12 pack hue and
    saturation as ``hue << 7 | sat`` (the 3B A1 layout) and byte 13 is value.
    """
    index = data.find(STATE_HEAD)
    if index < 0:
        return None
    body = data[index:]
    if len(body) < STATE_MIN_LEN or body[6] not in (0x23, 0x24):
        return None
    return SymphonyState(
        is_on=body[6] == POWER_ON,
        mode=body[7],
        effect_id=body[8],
        speed=body[9],
        hue=float(min(((body[11] << 8) | body[12]) >> 7, 359)),
        saturation=float(min(body[12] & 0x7F, 100)),
        value=min(body[13], 100),
    )


__all__ = [
    "AUTO",
    "AUTO_EFFECTS",
    "AUTO_INTERVAL",
    "CURRENT_COLOR",
    "DEFAULT_MUSIC_MODE",
    "DEFAULT_PALETTE",
    "EFFECTS",
    "MODE_EFFECT",
    "MODE_MUSIC",
    "MODE_STATIC",
    "MUSIC_MODES",
    "PALETTES",
    "SymphonyState",
    "TIMER_OPTIONS",
    "TimerSlot",
    "clear_slot_payload",
    "parse_timers",
    "set_time_payload",
    "timer_option",
    "timer_slot_payload",
    "color_record",
    "effect_payload",
    "find_state",
    "is_symphony",
    "music_payload",
    "palette_colors",
]
