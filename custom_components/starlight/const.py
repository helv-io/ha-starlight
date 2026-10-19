"""Constants for the Starlight integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "starlight"

CONF_PRODUCT_ID: Final = "product_id"
CONF_BLE_VERSION: Final = "ble_version"
CONF_FIRMWARE: Final = "firmware"
CONF_HEADER_VERSION: Final = "header_version"
CONF_DISCONNECT_DELAY: Final = "disconnect_delay"

HEADER_AUTO: Final = "auto"
DEFAULT_DISCONNECT_DELAY: Final = 30
DEFAULT_HEADER_VERSION: Final = HEADER_AUTO

SERVICE_UUID: Final = "0000ffff-0000-1000-8000-00805f9b34fb"
WRITE_UUID: Final = "0000ff01-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID: Final = "0000ff02-0000-1000-8000-00805f9b34fb"

# Transport opcodes. 0x0A asks for a reply. 0x0B is a one-way command.
# Stair hex commands use 0x0A because that is the app default. UNVERIFIED on the stair board.
OPCODE_QUERY: Final = 0x0A
OPCODE_COMMAND: Final = 0x0B
OPCODE_STAIR: Final = 0x0A

# Notification opcodes carrying a state upload.
# 0x15 is the response wrapper around an application payload such as EA 81.
OPCODE_STATE: Final = 0x0C
OPCODE_RESPONSE: Final = 0x15
OPCODE_STATE_V2: Final = 0x16

# How often to ask a connected controller for a fresh state upload.
STATE_POLL_SECONDS: Final = 30

MANUFACTURER: Final = "Starlight"
MIN_KELVIN: Final = 2700
MAX_KELVIN: Final = 6500

# Advertised names that would leak the upstream brand into the device title.
BANNED_NAME_PARTS: Final = ("istar", "zengge", "magichome", "magic home", "surplife", "lednet")

SIGNAL_STATE: Final = "starlight_state"

# Install and fault commands. The send-payload service refuses these unless forced.
BLOCKED_EF: Final = frozenset({0x11, 0x12, 0x13, 0x16, 0x17, 0x18, 0x19})
