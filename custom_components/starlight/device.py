"""One Bluetooth controller and the connection that talks to it.

Connections go through Home Assistant's bluetooth stack, so a local adapter
and an ESPHome proxy are the same call. The link is held only while a command
is in flight, then dropped after an idle delay so the proxy can serve other
devices. A lock keeps one command at a time on each address.
"""

from __future__ import annotations

import asyncio
import colorsys
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from .const import (
    BANNED_NAME_PARTS,
    CONF_BLE_VERSION,
    CONF_DISCONNECT_DELAY,
    CONF_FIRMWARE,
    CONF_HEADER_VERSION,
    CONF_PRODUCT_ID,
    DEFAULT_DISCONNECT_DELAY,
    DOMAIN,
    HEADER_AUTO,
    MANUFACTURER,
    MAX_KELVIN,
    MIN_KELVIN,
    NOTIFY_UUID,
    OPCODE_COMMAND,
    OPCODE_QUERY,
    OPCODE_STAIR,
    OPCODE_STATE,
    OPCODE_STATE_V2,
    WRITE_UUID,
)
from .protocol.advert import Advertisement, parse_stair_state
from .protocol.products import Product, get_product
from .protocol.rgb import (
    ADDRESSABLE_EFFECTS,
    MICROPHONE,
    SIMPLE_EFFECTS,
    SOLID,
    brightness_to_percent,
    color_payload,
    effect_payload,
    ha_hs_to_rgb,
    music_payload,
    parse_state_response,
    percent_to_brightness,
    percent_to_kelvin,
    power_payload,
    rgb_to_hs,
    state_query_payload,
    white_payload,
)
from .protocol.stair import (
    STAIR_MODES,
    StairMode,
    mode_by_key,
    modes_for_tab,
    pack_color,
    stair_install,
    stair_mode,
    stair_slow,
    stair_time,
)
from .protocol.transport import build_frame, header_version_for, payload_from_notify

_LOGGER = logging.getLogger(__name__)

Listener = Callable[[], None]


def friendly_name(raw: str | None, model: str) -> str:
    """Use the broadcast name unless it carries an upstream brand."""
    if not raw:
        return model
    lowered = raw.lower()
    if any(part in lowered for part in BANNED_NAME_PARTS):
        return model
    return raw


@dataclass
class RuntimeState:
    """Latest known light state. Commands update it before the notify comes back."""

    is_on: bool = False
    brightness: int = 255
    hs: tuple[float, float] = (0.0, 100.0)
    color_temp: int | None = None
    color_mode: str = "hs"
    effect: str | None = None
    effect_speed: int = 50
    mic: bool = False
    mic_sensitivity: int = 50
    remember: bool = False
    induction: bool = False
    slow_open: bool = False
    stair_count: int = 16
    run_time: int = 10
    hold_time: int = 10
    tab: str = "step"
    mode_key: str = "step"
    rssi: int | None = None
    last_notify: str | None = None
    listeners: list[Listener] = field(default_factory=list)


class StarlightDevice:
    """BLE session, state, and command helpers for one controller."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        data = entry.data
        self.address: str = data[CONF_ADDRESS]
        self.product_id: int | None = data.get(CONF_PRODUCT_ID)
        self.ble_version: int | None = data.get(CONF_BLE_VERSION)
        self.firmware: str | None = data.get(CONF_FIRMWARE)
        self.name: str = data.get(CONF_NAME) or self.address
        self.state = RuntimeState()
        self.last_error: str | None = None
        self.connected = False
        self._client = None
        self._lock = asyncio.Lock()
        self._seq = 0
        self._timer: asyncio.TimerHandle | None = None
        self._queried = False
        self._closing = False
        product = self.product
        if product is not None and product.kind == "stair":
            self.state.stair_count = product.channels or 16

    @property
    def product(self) -> Product | None:
        """Product record for the current id."""
        return get_product(self.product_id)

    @property
    def kind(self) -> str:
        """stair, addressable, rgb, rgbww, or cct. Unknown ids stay RGB."""
        product = self.product
        if product is not None:
            return product.kind
        return "rgb"

    @property
    def model(self) -> str:
        """Short model name for the device page."""
        product = self.product
        if product is None:
            return "Color light" if self.kind != "stair" else "Stair light"
        if product.kind == "stair" and product.channels:
            return f"Stair light {product.channels}"
        return product.model

    @property
    def header_version(self) -> int:
        """Frame version. The option overrides the advertisement."""
        choice = self.entry.options.get(CONF_HEADER_VERSION, HEADER_AUTO)
        if choice in (0, 1, "0", "1"):
            return int(choice)
        if self.ble_version is not None:
            return header_version_for(self.ble_version)
        # bleVersion below 8, and an unknown version, uses the V0 header.
        return 0

    @property
    def disconnect_delay(self) -> int:
        """Seconds to stay connected after the last command."""
        return int(self.entry.options.get(CONF_DISCONNECT_DELAY, DEFAULT_DISCONNECT_DELAY))

    @property
    def available(self) -> bool:
        """True when any adapter or proxy can currently see the address."""
        return bool(
            bluetooth.async_address_present(self.hass, self.address, connectable=False)
            or self.connected
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Registry record. The model comes from the product table."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.address)},
            connections={(CONNECTION_BLUETOOTH, self.address)},
            manufacturer=MANUFACTURER,
            model=self.model,
            name=self.name,
            sw_version=self.firmware,
        )

    def add_listener(self, listener: Listener) -> Callable[[], None]:
        """Register an entity refresh callback."""
        self.state.listeners.append(listener)

        def _remove() -> None:
            if listener in self.state.listeners:
                self.state.listeners.remove(listener)

        return _remove

    def _notify(self) -> None:
        for listener in list(self.state.listeners):
            listener()

    def apply_advert(self, advert: Advertisement) -> None:
        """Fold a broadcast into identity and, when present, power and color."""
        changed = False
        if advert.product_id and advert.product_id != self.product_id:
            self.product_id = advert.product_id
            changed = True
        if advert.ble_version != self.ble_version:
            self.ble_version = advert.ble_version
            changed = True
        if advert.firmware and advert.firmware != self.firmware:
            self.firmware = advert.firmware
            changed = True
        if advert.rssi is not None:
            self.state.rssi = advert.rssi
        if advert.power is not None:
            self.state.is_on = advert.power
        if advert.hs is not None:
            self.state.hs = advert.hs
            self.state.color_mode = "hs"
        elif advert.rgb is not None:
            self.state.hs = rgb_to_hs(*advert.rgb)
            self.state.color_mode = "hs"
            self.state.effect = None
        if advert.brightness_percent is not None:
            self.state.brightness = percent_to_brightness(advert.brightness_percent)
        if advert.color_mode == "cct" and advert.color_temp_percent is not None:
            self.state.color_temp = percent_to_kelvin(advert.color_temp_percent)
            self.state.color_mode = "color_temp"
        if advert.effect_id is not None:
            self.state.effect = self._effect_name(advert.effect_id)
        if changed:
            self._persist_identity()
        self._notify()

    def _persist_identity(self) -> None:
        data = dict(self.entry.data)
        data[CONF_PRODUCT_ID] = self.product_id
        data[CONF_BLE_VERSION] = self.ble_version
        data[CONF_FIRMWARE] = self.firmware
        self.hass.config_entries.async_update_entry(self.entry, data=data)

    def _effect_name(self, effect_id: int) -> str | None:
        table = ADDRESSABLE_EFFECTS if self.kind == "addressable" else SIMPLE_EFFECTS
        return table.get(effect_id)

    def effect_options(self, *, tab_only: bool = False) -> list[str]:
        """Effect names. The light lists every stair mode. The select stays on the tab."""
        if self.kind == "stair":
            modes = modes_for_tab(self.state.tab) if tab_only else STAIR_MODES
            return [mode.label for mode in modes]
        names = [SOLID]
        table = ADDRESSABLE_EFFECTS if self.kind == "addressable" else SIMPLE_EFFECTS
        names.extend(table.values())
        if self.supports_music:
            names.append(MICROPHONE)
        return names

    @property
    def supports_music(self) -> bool:
        """True when the product table lists a microphone function."""
        product = self.product
        return bool(product and product.music)

    @property
    def supports_color_temp(self) -> bool:
        """True for white and RGBWW products."""
        return self.kind in ("cct", "rgbww")

    @property
    def supports_color(self) -> bool:
        """True when the light can show a color, including stairs."""
        return self.kind != "cct"

    @property
    def supports_effects(self) -> bool:
        """Stairs and addressable lights always do. Other lights do when listed."""
        if self.kind in ("stair", "addressable"):
            return True
        product = self.product
        if product is None:
            return True
        return bool(product.best(0, ["scene_data_v2", "scene_data", "scene_data_v3"]))

    @property
    def stair_mode(self) -> StairMode:
        """Current stair mode, falling back to Step by step."""
        return mode_by_key(self.state.mode_key) or mode_by_key("step") or STAIR_MODES[0]

    async def async_shutdown(self) -> None:
        """Drop the link during unload."""
        self._closing = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        async with self._lock:
            await self._close_locked()

    async def async_turn_on(self, **kwargs) -> None:
        """Apply a light.turn_on request."""
        brightness = kwargs.get("brightness", self.state.brightness)
        self.state.brightness = brightness
        self.state.is_on = True
        if kwargs.get("hs_color") is not None:
            self.state.hs = kwargs["hs_color"]
            self.state.color_mode = "hs"
            self.state.effect = None
        if kwargs.get("color_temp_kelvin") is not None:
            self.state.color_temp = kwargs["color_temp_kelvin"]
            self.state.color_mode = "color_temp"
            self.state.effect = None
        if kwargs.get("effect"):
            self._set_effect_local(kwargs["effect"])
        self._notify()
        if self.kind == "stair":
            await self._send(power_payload(self.product, True), OPCODE_STAIR)
            await self._send(self._stair_payload(), OPCODE_STAIR)
            return
        await self._send(power_payload(self.product, True), OPCODE_COMMAND)
        await self._send_visual()

    async def async_turn_off(self) -> None:
        """Switch the light off."""
        self.state.is_on = False
        self._notify()
        opcode = OPCODE_STAIR if self.kind == "stair" else OPCODE_COMMAND
        await self._send(power_payload(self.product, False), opcode)

    async def async_set_effect(self, name: str) -> None:
        """Select an effect or a stair mode."""
        self._set_effect_local(name)
        self.state.is_on = True
        self._notify()
        if self.kind == "stair":
            await self._send(self._stair_payload(), OPCODE_STAIR)
            return
        await self._send_visual()

    async def async_set_tab(self, tab: str) -> None:
        """Change the stair tab and send the first mode on that tab."""
        self.state.tab = tab
        modes = modes_for_tab(tab)
        if modes:
            self.state.mode_key = modes[0].key
        self.state.is_on = True
        self._notify()
        await self._send(self._stair_payload(), OPCODE_STAIR)

    async def async_set_speed(self, speed: int) -> None:
        """Set effect speed and resend the current effect."""
        self.state.effect_speed = max(1, min(100, int(speed)))
        self._notify()
        if self.state.effect and self.state.effect not in (SOLID, None):
            await self._send_visual()

    async def async_set_induction(self, enabled: bool) -> None:
        """Enable or disable the stair motion sensor."""
        self.state.induction = enabled
        self._notify()
        await self._send(self._stair_payload(), OPCODE_STAIR)

    async def async_set_slow(self, enabled: bool) -> None:
        """Enable or disable soft start."""
        self.state.slow_open = enabled
        self._notify()
        await self._send(stair_slow(enabled), OPCODE_STAIR)

    async def async_set_stair_count(self, count: int) -> None:
        """Send the install step-count command. The field order is unverified."""
        self.state.stair_count = int(count)
        self._notify()
        await self._send(stair_install(int(count)), OPCODE_STAIR)

    async def async_set_run_time(self, value: int) -> None:
        """Send the time-tab command. Which byte is run time is unverified."""
        self.state.run_time = int(value)
        self._notify()
        await self._send(stair_time(self.state.run_time, self.state.hold_time), OPCODE_STAIR)

    async def async_set_hold_time(self, value: int) -> None:
        """Send the time-tab command. Which byte is hold time is unverified."""
        self.state.hold_time = int(value)
        self._notify()
        await self._send(stair_time(self.state.run_time, self.state.hold_time), OPCODE_STAIR)

    async def async_sweep(self, direction: str) -> None:
        """Run one stair sweep.

        UNVERIFIED: direction is the EF 10 p3 byte. 0 is top to bottom,
        1 is bottom to top. The mode stays on Step for the sweep.
        """
        down = direction in ("down", "top_to_bottom", "top")
        self.state.is_on = True
        self.state.tab = "step"
        self.state.mode_key = "step"
        self._notify()
        await self._send(self._stair_payload(p3=0 if down else 1), OPCODE_STAIR)

    async def async_set_mic(self, enabled: bool) -> None:
        """Turn the built-in microphone on or off."""
        self.state.mic = enabled
        if enabled:
            self.state.effect = MICROPHONE
            self.state.is_on = True
        self._notify()
        await self._send_visual()

    async def async_set_sensitivity(self, value: int) -> None:
        """Set microphone sensitivity and resend when the mic is on."""
        self.state.mic_sensitivity = max(1, min(100, int(value)))
        self._notify()
        if self.state.mic:
            await self._send_visual()

    async def async_set_remember(self, remember: bool) -> None:
        """Remember the next color across power loss. Uses the 0x31 persist flag."""
        self.state.remember = remember
        self._notify()
        if self.kind != "stair":
            await self._send_visual()

    async def async_send_payload(self, payload: bytes, opcode: int | None = None) -> str:
        """Send a raw payload and return the frame hex. Used by the service."""
        chosen = OPCODE_STAIR if self.kind == "stair" else OPCODE_COMMAND
        if opcode is not None:
            chosen = opcode
        frame = await self._send(payload, chosen)
        return frame.hex()

    def _set_effect_local(self, name: str) -> None:
        if self.kind == "stair":
            mode = mode_by_key(name)
            if mode is None:
                raise HomeAssistantError(f"Unknown effect {name}")
            self.state.mode_key = mode.key
            self.state.tab = mode.tab
            self.state.effect = mode.label
            return
        if name in (SOLID, "solid", "none", "None"):
            self.state.effect = None
            self.state.mic = False
            return
        if name == MICROPHONE:
            self.state.effect = MICROPHONE
            self.state.mic = True
            return
        self.state.effect = name
        self.state.mic = False

    def _stair_payload(self, p3: int = 0) -> bytes:
        mode = self.stair_mode
        percent = brightness_to_percent(self.state.brightness)
        hue, sat = self.state.hs
        return stair_mode(
            {"step": 0, "stream": 1, "time": 2}[mode.tab],
            percent,
            self.state.induction,
            mode.wire,
            pack_color(int(hue), int(sat), 100),
            p3=p3,
        )

    def _effect_id(self) -> int | None:
        name = self.state.effect
        if not name or name in (SOLID, MICROPHONE):
            return None
        table = ADDRESSABLE_EFFECTS if self.kind == "addressable" else SIMPLE_EFFECTS
        for effect_id, label in table.items():
            if label == name:
                return effect_id
        return None

    async def _send_visual(self) -> None:
        percent = brightness_to_percent(self.state.brightness)
        red, green, blue = ha_hs_to_rgb(*self.state.hs)
        if self.state.mic or self.state.effect == MICROPHONE:
            await self._send(
                music_payload(
                    self.product,
                    True,
                    self.state.mic_sensitivity,
                    red,
                    green,
                    blue,
                    percent,
                ),
                OPCODE_COMMAND,
            )
            return
        effect_id = self._effect_id()
        if effect_id is not None:
            payload = effect_payload(self.product, effect_id, self.state.effect_speed, percent)
            if payload is not None:
                await self._send(payload, OPCODE_COMMAND)
                return
        if self.state.color_mode == "color_temp" and self.supports_color_temp:
            kelvin = self.state.color_temp or 4000
            kelvin = max(MIN_KELVIN, min(MAX_KELVIN, kelvin))
            payload = white_payload(
                self.product,
                kelvin,
                percent,
                ble_version=self.ble_version,
                persist=self.state.remember,
            )
        else:
            payload = color_payload(
                self.product,
                red,
                green,
                blue,
                percent,
                ble_version=self.ble_version,
                persist=self.state.remember,
            )
        await self._send(payload, OPCODE_COMMAND)

    async def _send(self, payload: bytes, opcode: int) -> bytes:
        async with self._lock:
            if self._closing:
                raise HomeAssistantError("Light is shutting down")
            await self._connect_locked()
            frame = await self._write_locked(payload, opcode)
            self._schedule_disconnect()
            return frame

    async def _connect_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._client is not None and self._client.is_connected:
            return
        device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if device is None:
            raise HomeAssistantError(
                f"{self.name} is not on a connectable Bluetooth adapter or proxy"
            )

        def _fresh():
            return bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )

        try:
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                self.name,
                disconnected_callback=self._on_disconnected,
                max_attempts=3,
                use_services_cache=True,
                ble_device_callback=_fresh,
            )
            await self._client.start_notify(NOTIFY_UUID, self._on_notify)
            # The stack needs a moment to enable notifications before the first write.
            await asyncio.sleep(0.1)
            self.connected = True
            self.last_error = None
        except (TimeoutError, BleakError, OSError) as err:
            self._client = None
            self.connected = False
            self.last_error = str(err)
            _LOGGER.warning("Could not connect to %s: %s", self.address, err)
            raise HomeAssistantError(f"Could not connect to {self.name}") from err

        if not self._queried:
            self._queried = True
            try:
                await self._write_locked(state_query_payload(), OPCODE_QUERY)
                await asyncio.sleep(0.2)
            except HomeAssistantError:
                _LOGGER.debug("State query failed for %s", self.address)

    async def _write_locked(self, payload: bytes, opcode: int) -> bytes:
        self._seq = (self._seq + 1) & 0xFF
        if self._seq == 0:
            self._seq = 1
        frame = build_frame(payload, self.header_version, self._seq, opcode)
        client = self._client
        if client is None or not client.is_connected:
            raise HomeAssistantError(f"{self.name} dropped the Bluetooth link")
        _LOGGER.info(
            "starlight -> %s v%s seq %s %s",
            self.address,
            self.header_version,
            self._seq,
            frame.hex(),
        )
        try:
            await client.write_gatt_char(WRITE_UUID, frame, response=False)
        except (TimeoutError, BleakError, OSError) as err:
            self.last_error = str(err)
            self.connected = False
            self._client = None
            _LOGGER.warning("Write to %s failed: %s", self.address, err)
            raise HomeAssistantError(f"Could not send a command to {self.name}") from err
        return frame

    def _schedule_disconnect(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        delay = self.disconnect_delay
        if delay <= 0:
            self.hass.async_create_task(self._disconnect_soon())
            return
        self._timer = self.hass.loop.call_later(delay, self._disconnect_soon_threadsafe)

    def _disconnect_soon_threadsafe(self) -> None:
        self.hass.async_create_task(self._disconnect_soon())

    async def _disconnect_soon(self) -> None:
        if self._closing:
            return
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        client = self._client
        self._client = None
        self.connected = False
        self._queried = False
        if client is None:
            return
        try:
            if client.is_connected:
                await client.disconnect()
        except (BleakError, OSError):
            _LOGGER.debug("Disconnect from %s failed", self.address)

    def _on_disconnected(self, _client) -> None:
        self.connected = False
        self._client = None
        self._queried = False

    def _on_notify(self, _char, data: bytearray) -> None:
        raw = bytes(data)
        self.hass.loop.call_soon_threadsafe(self._handle_notify, raw)

    @callback
    def _handle_notify(self, raw: bytes) -> None:
        opcode, payload = payload_from_notify(raw)
        self.state.last_notify = raw.hex()
        _LOGGER.debug(
            "starlight <- %s opcode %s %s",
            self.address,
            None if opcode is None else f"{opcode:02X}",
            payload.hex(),
        )
        if payload and payload[0] == 0x81:
            self._apply_standard_state(payload)
            return
        if payload and self.kind == "stair" and opcode in (OPCODE_STATE, OPCODE_STATE_V2):
            self._apply_stair_state(payload)
            return
        if payload and opcode in (OPCODE_STATE, OPCODE_STATE_V2):
            self._apply_standard_state(payload)
            return
        self._notify()

    def _apply_standard_state(self, payload: bytes) -> None:
        parsed = parse_state_response(payload)
        if parsed is None:
            self._notify()
            return
        self.state.is_on = bool(parsed["is_on"])
        if parsed["is_rgb"]:
            self.state.hs = rgb_to_hs(parsed["r"], parsed["g"], parsed["b"])
            self.state.color_mode = "hs"
            self.state.effect = None
            _hue, _sat, value = _value_from_rgb(parsed["r"], parsed["g"], parsed["b"])
            self.state.brightness = percent_to_brightness(round(value * 100))
        elif parsed["is_white"]:
            self.state.color_mode = "color_temp"
            self.state.brightness = percent_to_brightness(parsed["value1"])
        elif parsed["is_effect"] and parsed["effect_id"] is not None:
            name = self._effect_name(parsed["effect_id"])
            if name:
                self.state.effect = name
        self._notify()

    def _apply_stair_state(self, payload: bytes) -> None:
        """Apply a stair state upload when the app's 0x23/0x24 flag is present."""
        parsed = parse_stair_state(payload)
        if parsed is not None:
            power, hs = parsed
            self.state.is_on = power
            if hs is not None:
                self.state.hs = hs
        self._notify()


def _value_from_rgb(red: int, green: int, blue: int) -> tuple[float, float, float]:
    hue, sat, value = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
    return hue, sat, value
