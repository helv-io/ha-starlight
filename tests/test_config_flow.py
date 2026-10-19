"""Config flow tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResultType

from custom_components.starlight.const import CONF_PRODUCT_ID, DOMAIN


@pytest.fixture(autouse=True)
def _bluetooth_dependencies():
    """Satisfy the bluetooth dependency chain without a local adapter."""
    with (
        patch("homeassistant.components.usb.async_setup", return_value=True),
        patch("homeassistant.components.bluetooth.async_setup", return_value=True),
        patch("homeassistant.components.bluetooth_adapters.async_setup", return_value=True),
        patch("custom_components.starlight.async_register_callback", return_value=lambda: None),
        patch(
            "custom_components.starlight.device.bluetooth.async_address_present",
            return_value=True,
        ),
    ):
        yield


def _payload() -> bytes:
    data = bytearray(27)
    data[1] = 8
    data[2:8] = bytes.fromhex("0865F01CE65B")
    data[8] = 0x02
    data[9] = 0x14
    data[10] = 0x0C
    data[14] = 0x23
    return bytes(data)


def _advert(name: str, manufacturer_data: dict[int, bytes]) -> AdvertisementData:
    return AdvertisementData(
        local_name=name,
        manufacturer_data=manufacturer_data,
        service_data={},
        service_uuids=["0000ffff-0000-1000-8000-00805f9b34fb"],
        tx_power=None,
        rssi=-48,
        platform_data=(),
    )


def _info(address: str = "08:65:F0:1C:E6:5B", name: str = "Stair") -> BluetoothServiceInfoBleak:
    return BluetoothServiceInfoBleak.from_device_and_advertisement_data(
        BLEDevice(address, name, {}),
        _advert(name, {0x5A01: _payload()}),
        "local",
        0.0,
        True,
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the integration from this repo."""
    yield


async def test_bluetooth_discovery_creates_entry(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ADDRESS] == "08:65:F0:1C:E6:5B"
    assert result["data"][CONF_PRODUCT_ID] == 532


async def test_bluetooth_discovery_rejects_other_devices(hass) -> None:
    info = BluetoothServiceInfoBleak.from_device_and_advertisement_data(
        BLEDevice("AA:BB:CC:DD:EE:FF", "Other", {}),
        _advert("Other", {76: b"\x01\x02"}),
        "local",
        0.0,
        True,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_user_manual_address(hass) -> None:
    with patch(
        "custom_components.starlight.config_flow.async_discovered_service_info",
        return_value=[_info()],
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"manual_address": "11:22:33:44:55:66"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ADDRESS] == "11:22:33:44:55:66"


async def test_user_rejects_bad_address(hass) -> None:
    with patch(
        "custom_components.starlight.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"manual_address": "not-a-mac"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["manual_address"] == "invalid_address"


async def test_duplicate_aborts(hass) -> None:
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_info()
    )
    await hass.config_entries.flow.async_configure(first["flow_id"], {})
    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=_info()
    )
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_configured"
