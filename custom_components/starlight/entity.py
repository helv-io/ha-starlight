"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .device import StarlightDevice


class StarlightEntity(Entity):
    """Base entity bound to one controller."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: StarlightDevice) -> None:
        self._device = device

    @property
    def available(self) -> bool:
        return self._device.available

    @property
    def device_info(self):
        return self._device.device_info

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._device.add_listener(self._handle_update))

    def _handle_update(self) -> None:
        self.async_write_ha_state()
