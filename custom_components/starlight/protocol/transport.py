"""ZGHB single-segment transport frames.

V0 matches the frames exercised by the LEDnetWF integration on real RGB
controllers. V1 adds the 16-bit length used when the advertisement
bleVersion is 8 or higher. Multi-segment reassembly is not implemented.
Stair and color commands used here are short enough for one segment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

OPCODE_STATE = 0x0C
OPCODE_RESPONSE = 0x15
OPCODE_STATE_V2 = 0x16


def header_version_for(ble_version: int | None) -> int:
    """Return 1 when the controller speaks the V1 header."""
    if ble_version is None:
        return 0
    return 1 if ble_version >= 8 else 0


def build_frame(payload: bytes, version: int, seq: int, opcode: int) -> bytes:
    """Wrap a payload in one ZGHB segment.

    V0 (bleVersion < 8):  00 | seq | 80 00 | len_hi len_lo | (len+1) | opcode | payload
    V1 (bleVersion >= 8): 01 | seq | 80 00 | len_hi len_lo | (len+1)_hi (len+1)_lo | opcode | payload
    """
    if version not in (0, 1):
        raise ValueError(f"unsupported frame version {version}")
    if not payload:
        raise ValueError("empty payload")
    if len(payload) > 200:
        raise ValueError("payload too long for a single segment")

    length = len(payload)
    seq &= 0xFF
    opcode &= 0xFF
    if version == 0:
        header = bytes(
            (
                0x00,
                seq,
                0x80,
                0x00,
                (length >> 8) & 0xFF,
                length & 0xFF,
                (length + 1) & 0xFF,
                opcode,
            )
        )
    else:
        size = length + 1
        header = bytes(
            (
                0x01,
                seq,
                0x80,
                0x00,
                (length >> 8) & 0xFF,
                length & 0xFF,
                (size >> 8) & 0xFF,
                size & 0xFF,
                opcode,
            )
        )
    return header + payload


@dataclass(frozen=True)
class Frame:
    """One decoded notification segment."""

    version: int
    seq: int
    opcode: int
    payload: bytes
    segmented: bool


def parse_frame(data: bytes) -> Frame | None:
    """Decode a notify packet. Segmented packets are flagged and not rebuilt."""
    if len(data) < 8:
        return None
    ctrl = data[0]
    version = ctrl & 0x03
    segmented = bool(ctrl & 0x40)
    seq = data[1]
    if version == 0:
        length = (data[4] << 8) | data[5]
        opcode = data[7]
        payload = data[8 : 8 + length]
    elif version == 1:
        if len(data) < 9:
            return None
        length = (data[4] << 8) | data[5]
        opcode = data[8]
        payload = data[9 : 9 + length]
    else:
        return None
    if not payload and length:
        payload = data[8:] if version == 0 else data[9:]
    return Frame(version, seq, opcode, bytes(payload), segmented)


def payload_from_notify(data: bytes) -> tuple[int | None, bytes]:
    """Return (opcode, command bytes) from a notification.

    JSON replies shaped as {"payload": "<hex>"} are unwrapped. A bare 0x81
    state block is accepted when the transport header is missing.
    """
    frame = parse_frame(data)
    if frame is None:
        if data and data[0] == 0x81:
            return None, bytes(data)
        return None, b""
    payload = frame.payload
    if payload and payload[0] in (0x7B, 0x5B):
        try:
            body = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = None
        if isinstance(body, dict) and isinstance(body.get("payload"), str):
            try:
                payload = bytes.fromhex(body["payload"])
            except ValueError:
                pass
    opcode = frame.opcode
    # Opcode 0x15 wraps the application payload. When that payload is itself
    # a transport frame, strip the inner header once.
    if opcode == OPCODE_RESPONSE and len(payload) >= 8 and payload[2:4] == b"\x80\x00":
        nested = parse_frame(payload)
        if nested is not None and nested.payload:
            return nested.opcode, nested.payload
    return opcode, payload
