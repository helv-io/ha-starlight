"""Fill command templates from the product database.

Template substitution matches the LEDnetWF command builder: a placeholder
written once is one byte, and the same placeholder written N times is one
big-endian integer of N bytes. The checksum is the sum of the bytes.
"""

from __future__ import annotations

import re


class CommandError(Exception):
    """A template could not be filled."""


def build_from_template(cmd_form: str, params: dict[str, int], need_checksum: bool) -> bytes:
    """Substitute {name} placeholders and optionally append a checksum."""
    result = cmd_form
    names = re.findall(r"\{(\w+)\}", cmd_form)
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    for name, count in counts.items():
        value = int(params.get(name, 0))
        placeholder = "{" + name + "}"
        if count == 1:
            result = result.replace(placeholder, f"{value & 0xFF:02x}")
            continue
        width = (1 << (count * 8)) - 1
        value &= width
        for shift in range(count - 1, -1, -1):
            byte = (value >> (shift * 8)) & 0xFF
            result = result.replace(placeholder, f"{byte:02x}", 1)
    if "{" in result:
        raise CommandError(f"unfilled template {result}")
    try:
        payload = bytes.fromhex(result)
    except ValueError as err:
        raise CommandError(f"bad hex from template {result}") from err
    if need_checksum:
        payload += bytes((sum(payload) & 0xFF,))
    return payload
