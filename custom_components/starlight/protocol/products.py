"""Product table ported from the controller app database."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).parent.parent / "data"


@dataclass(frozen=True)
class CommandForm:
    """One hex command template."""

    cmd: str
    checksum: bool
    opcode: int | None = None


@dataclass(frozen=True)
class Product:
    """What we know about one product id."""

    product_id: int
    kind: str
    model: str
    category: str
    state: str
    states: tuple[str, ...]
    functions: frozenset[str]
    music: bool
    ble: bool
    channels: int
    forms: dict[str, CommandForm] = field(default_factory=dict)
    min_fw: dict[str, int] = field(default_factory=dict)

    def supports(self, code: str, firmware: int = 0) -> bool:
        """Return True when this product lists the function."""
        if code not in self.functions and code not in self.forms:
            return False
        return firmware >= self.min_fw.get(code, 0)

    def best(self, firmware: int, preferences: list[str]) -> str | None:
        """Pick the first supported function code."""
        for code in preferences:
            if self.supports(code, firmware):
                return code
        return None


def _form_from(raw: dict[str, Any]) -> CommandForm:
    custom = raw.get("customParams") or {}
    checksum = bool(raw.get("needChecksum") or raw.get("checksum") or custom.get("needChecksum"))
    return CommandForm(
        cmd=raw.get("cmdForm") or raw.get("cmd") or "",
        checksum=checksum,
        opcode=raw.get("opcode"),
    )


# The app's stair_16_32 function is the wide stair controller. A stair product
# without that function is the 16-channel controller.
_WIDE_STAIR_FUNCTION = "stair_16_32"
_NARROW_STAIR_CHANNELS = 16
_WIDE_STAIR_CHANNELS = 32


def _is_stair(category: str, state: str, states: tuple[str, ...]) -> bool:
    """True when the category or a state protocol is a stair light."""
    return any("stair" in name.lower() for name in (category, state, *states))


def _kind_for(raw: dict[str, Any], category: str, state: str, states: tuple[str, ...]) -> str:
    """Kind from the product table.

    Stair follows the category and state protocol. Every other kind is the
    classification already stored from the full product database.
    """
    if _is_stair(category, state, states):
        return "stair"
    return raw.get("kind") or "rgb"


def _channels_for(kind: str, functions: frozenset[str], stored: int) -> int:
    """Channel count. Stairs come from the function list, not a model id."""
    if kind != "stair":
        return stored
    if _WIDE_STAIR_FUNCTION in functions:
        return _WIDE_STAIR_CHANNELS
    return _NARROW_STAIR_CHANNELS


@lru_cache(maxsize=1)
def _load() -> tuple[dict[int, Product], dict[str, CommandForm]]:
    products_raw = json.loads((_DATA / "products.json").read_text(encoding="utf-8"))
    commands_raw = json.loads((_DATA / "dp_cmd.json").read_text(encoding="utf-8"))
    global_forms = {key: _form_from(value) for key, value in commands_raw.items()}
    products: dict[int, Product] = {}
    for key, raw in products_raw.items():
        forms = {name: _form_from(spec) for name, spec in (raw.get("forms") or {}).items()}
        category = raw.get("category") or ""
        state = raw.get("state") or ""
        states = tuple(raw.get("states") or ())
        functions = frozenset(raw.get("functions") or ())
        kind = _kind_for(raw, category, state, states)
        products[int(key)] = Product(
            product_id=int(key),
            kind=kind,
            model=raw.get("model") or "Color light",
            category=category,
            state=state,
            states=states,
            functions=functions,
            music=bool(raw.get("music")),
            ble=bool(raw.get("ble")),
            channels=_channels_for(kind, functions, int(raw.get("channels") or 0)),
            forms=forms,
            min_fw={str(k): int(v) for k, v in (raw.get("min_fw") or {}).items()},
        )
    return products, global_forms


def load_tables() -> None:
    """Read the product and command tables. Call this off the event loop."""
    _load()


def get_product(product_id: int | None) -> Product | None:
    """Return the product record, or None when the id is unknown."""
    if product_id is None:
        return None
    return _load()[0].get(product_id)


def command_form(product: Product | None, code: str) -> CommandForm | None:
    """Resolve a template. Device forms win over the shared table."""
    if product is not None and code in product.forms:
        return product.forms[code]
    return _load()[1].get(code)


def known_product_ids() -> list[int]:
    """Return every product id in the table."""
    return sorted(_load()[0])
