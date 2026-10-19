# Starlight

Local Bluetooth lights for Home Assistant. Starlight talks to the controller
over the Home Assistant `bluetooth` integration, so a built-in adapter and an
ESPHome Bluetooth proxy are the same path. Nothing is sent to a cloud account.

The integration is installable with HACS as a custom integration. Domain:
`starlight`.

It is compatible with the controllers sold under the iStar Lighting app
(Android package `com.istarlighting.magichome2`), which is a Zengge / Magic
Home 2 / Surplife white label. Device names in Home Assistant stay generic.
Broadcast names that contain those brands are replaced with the model from
the product table.

## Install

1. In HACS, choose Integrations, then the menu, then Custom repositories.
2. Add `https://github.com/helv-io/ha-starlight` as an Integration.
3. Install Starlight and restart Home Assistant.
4. Go to Settings, Devices & services, Add integration, and search for Starlight.

A controller that is already advertising is offered automatically. You can
also type its Bluetooth address.

## What you get

Stair controllers (category and state protocol from the product table;
16 channels, or 32 when the product lists `stair_16_32`):

- Light with on, off, brightness, color, and every stair effect
- Effect tab (Step, Stream, Time) and the effects on that tab
- Step count (disabled until enabled), run time, and hold time
- Motion trigger and soft start
- Sweep down and sweep up buttons
- Service `starlight.sweep` with direction `down` or `up`

Other controllers in the product table (RGB, RGBW, CCT, addressable):

- Light with color or color temperature, brightness, and effects
- Effect speed
- Microphone and mic sensitivity, when the product lists a microphone
- Power-on color

Every device also has a signal-strength sensor, a last-notification sensor,
and a diagnostics dump. The Bluetooth address is removed from diagnostics.

Options on the device page:

- Frame version. Auto follows the broadcast. Choose 0 or 1 only when commands are ignored.
- Idle disconnect. Seconds to keep the link after a command. 0 drops it at once.

`starlight.send_payload` sends hex bytes without the frame header. Commands
that change wiring or step setup are refused unless Allow install commands
is on.

## Verified and assumed

RGB behavior below is the behavior already exercised by
[lednetwf_ble](https://github.com/8none1/lednetwf_ble) on real controllers.
Stair commands follow the controller app. A live stair advert was accepted
as V0 writes; the light's visual response to those writes is still unconfirmed.
See NOTICE for the MIT attribution.

| Piece | Status |
| --- | --- |
| GATT service `0000ffff-0000-1000-8000-00805f9b34fb`, write `…ff01…`, notify `…ff02…` | Verified by lednetwf_ble on RGB controllers, and by the app |
| V0 frame (`bleVersion` below 8): `00 \| seq \| 80 00 \| len \| (len+1) \| opcode \| payload` | Verified by lednetwf_ble. Stair `bleVersion` 7 uses this header |
| V1 frame (`bleVersion` 8 and above): 16-bit `(len+1)` | Taken from the app encoder |
| Manufacturer-only 27-byte identity: product id at bytes 8-9, power `0x23` / `0x24` at byte 14 when `bleVersion` is 5 or higher | Verified by lednetwf_ble for RGB |
| Service data `00005axx` (UUID already removed): status, ble version, MAC, product id, firmware, led version | From the app parser. This identity wins over the manufacturer block, which is then state |
| Legacy power `71 23 0F` / `71 24 0F` plus checksum, state query `81 8A 8B`, color `31` / `3B`, effects `42` and `61`, music `73` | Verified by lednetwf_ble. Which product receives which form is chosen from the product table |
| Stair kind from category or state protocol `wifibleStairLight`. 32 channels when the function list contains `stair_16_32`, otherwise 16 | From the app product database |
| Stair power, when `switch_led_v3` is listed: `E0 01 01` plus `0x23`/`0x24` and ten zero bytes | From the app builder. A controller accepted the on form |
| Other products keep the shared `switch_led_v3` template | From the command table |
| Stair payloads start with `EF 10` (mode), `EF 20` (carrier, same layout), `EF 11` (install), `EF 14` (time), `EF 15` (soft start) | From the app builder |
| EF 10 field order: tab, brightness, direction byte, motion flag `0x23`/`0x24`, color type, color count, mode, color | From the app builder. Direction `0` down / `1` up, and the tab grouping, follow the app's mode names |
| EF 11 first 16-bit field is the step count | Assumption. The step-count entity is disabled until enabled |
| EF 14 first two payload bytes are run time and hold time | Assumption |
| Stair commands use write opcode `0x0A` | From the app default. RGB commands use `0x0B` |
| Stair color is hue (9 bits), saturation (7 bits), value | From the app. Two extra white bytes the app sometimes appends are omitted |
| Stair state flag `0x23`/`0x24` at byte 2, hue/saturation at bytes 8-9 | From the app. Applied only when that flag is present |
| Default frame version with no advertisement yet is V0 | `bleVersion` below 8 uses V0 |

If a command is ignored, set Frame version to the other value and try again.
`starlight.send_payload` is there so a captured payload can be tried without
a code change.

## Development

```bash
pip install -r requirements_test.txt
ruff check custom_components tests
pytest
```

GitHub Actions runs hassfest, HACS validation, ruff, and pytest.
