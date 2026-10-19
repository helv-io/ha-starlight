"""Local command codec for Starlight lights.

Transport framing for BLE version 8 and above, stair payloads, and the
advertisement layout come from the controller app. RGB, CCT, and effect
payloads follow the MIT-licensed LEDnetWF work. See NOTICE.
"""

from .advert import Advertisement, parse_advertisement, parse_manufacturer_data
from .commands import CommandError, build_from_template
from .products import Product, get_product
from .rgb import (
    color_payload,
    effect_payload,
    music_payload,
    parse_state_response,
    power_payload,
    state_query_payload,
)
from .stair import (
    STAIR_MODES,
    StairMode,
    mode_by_key,
    stair_install,
    stair_mode,
    stair_slow,
    stair_time,
)
from .transport import build_frame, header_version_for, parse_frame

__all__ = [
    "STAIR_MODES",
    "Advertisement",
    "CommandError",
    "Product",
    "StairMode",
    "build_frame",
    "build_from_template",
    "color_payload",
    "effect_payload",
    "get_product",
    "header_version_for",
    "mode_by_key",
    "music_payload",
    "parse_advertisement",
    "parse_frame",
    "parse_manufacturer_data",
    "parse_state_response",
    "power_payload",
    "stair_install",
    "stair_mode",
    "stair_slow",
    "stair_time",
    "state_query_payload",
]
