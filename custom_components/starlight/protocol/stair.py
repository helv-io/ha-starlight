"""Stair-light payloads. Command bytes start with 0xEF.

The byte layout of EF 10, EF 11, EF 14, and EF 15 is taken from the app
builder. Which field is the step count, which EF 14 byte is run time, and
how a sweep encodes direction are assumptions. Search for UNVERIFIED.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StairMode:
    """One stair effect and the tab it belongs to in the app."""

    key: str
    wire: int
    label: str
    tab: str


# Tab assignment is UNVERIFIED. The wire values are from the app enum.
# singleStep shares wire 2 with stepByStep. threeFollow shares wire 3 with follow.
STAIR_MODES: tuple[StairMode, ...] = (
    StairMode("step", 2, "Step", "step"),
    StairMode("follow", 3, "Follow", "step"),
    StairMode("interval", 4, "Interval", "step"),
    StairMode("two_step", 13, "Two step", "step"),
    StairMode("single_follow", 14, "Single follow", "step"),
    StairMode("stream", 5, "Stream", "stream"),
    StairMode("stars", 6, "Stars", "stream"),
    StairMode("alternate", 7, "Alternate", "stream"),
    StairMode("chase", 12, "Chase", "stream"),
    StairMode("jump", 10, "Jump", "stream"),
    StairMode("random", 9, "Random", "stream"),
    StairMode("full", 1, "Full", "time"),
    StairMode("fade_forward", 11, "Fade forward", "time"),
    StairMode("fade_back", 8, "Fade back", "time"),
)

TABS = {"step": 0, "stream": 1, "time": 2}
_BY_KEY = {mode.key: mode for mode in STAIR_MODES}
_BY_LABEL = {mode.label: mode for mode in STAIR_MODES}


def mode_by_key(key: str) -> StairMode | None:
    """Look up a mode by its key or its label."""
    return _BY_KEY.get(key) or _BY_LABEL.get(key)


def modes_for_tab(tab: str) -> tuple[StairMode, ...]:
    """Return the modes grouped under one tab."""
    return tuple(mode for mode in STAIR_MODES if mode.tab == tab)


def pack_color(hue: int, saturation: int, value: int = 100) -> bytes:
    """Pack one stair color record.

    Hue uses 9 bits and saturation 7 bits, then a value byte. The app may
    append two more white bytes. Those are omitted until a capture shows them.
    """
    packed = ((hue & 0x1FF) << 7) | (saturation & 0x7F)
    return bytes(((packed >> 8) & 0xFF, packed & 0xFF, value & 0xFF))


def stair_mode(
    tab: int,
    brightness: int,
    flag_on: bool,
    mode: int,
    colors: bytes = b"",
    *,
    p3: int = 0,
    color_type: int = 0,
    n_colors: int = 1,
) -> bytes:
    """EF 10 stair mode setting.

    p3 is UNVERIFIED. Sweep uses 0 for top to bottom and 1 for bottom to top.
    flag_on encodes the motion-sensor enable as 0x23 or 0x24.
    """
    return (
        bytes(
            (
                0xEF,
                0x10,
                tab & 0xFF,
                max(0, min(100, brightness)) & 0xFF,
                p3 & 0xFF,
                0x23 if flag_on else 0x24,
                color_type & 0xFF,
                n_colors & 0xFF,
                mode & 0xFF,
            )
        )
        + colors
    )


def stair_install(count: int, stream: int = 1) -> bytes:
    """EF 11 install setting.

    UNVERIFIED: the first 16-bit field is treated as the step count and the
    second as the stream count. The two single bytes are sent as 0.
    """
    count = max(1, min(32, count))
    stream = max(0, min(32, stream))
    return bytes(
        (
            0xEF,
            0x11,
            0x00,
            (count >> 8) & 0xFF,
            count & 0xFF,
            0x00,
            (stream >> 8) & 0xFF,
            stream & 0xFF,
        )
    )


def stair_time(run_time: int, hold_time: int) -> bytes:
    """EF 14 time-tab setting.

    UNVERIFIED: byte 0 is run time and byte 1 is hold time. The other four
    bytes are sent as 0.
    """
    return bytes(
        (
            0xEF,
            0x14,
            max(0, min(100, run_time)) & 0xFF,
            max(0, min(100, hold_time)) & 0xFF,
            0,
            0,
            0,
            0,
        )
    )


def stair_slow(enabled: bool) -> bytes:
    """EF 15 soft start. 0x23 enables it and 0x24 disables it."""
    return bytes((0xEF, 0x15, 0x23 if enabled else 0x24))
