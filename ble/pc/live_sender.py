"""Experimental Windows BLE sender; run only after the mock security trial.

The account remains on this computer. Only protocol.py's display fields cross
the encrypted Bluetooth link; this version does not use the Wi-Fi bridge.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
from pathlib import Path
import sys
import threading

from demo_sender import request_windows_service_access, send_snapshot
from protocol import SERVICE_UUID, STATUS_UUID, WRITE_UUID, make_payload

BLE_ROOT = Path(__file__).resolve().parents[1]


async def require_windows_authenticated_pairing(client):
    """Fail closed unless Windows reports a bonded, authenticated peer.

    Bleak 3.0.1 exposes the WinRT requester through its backend; if that API
    changes, fail rather than silently relax security. The access protection
    level is additionally required on both GATT characteristics before I/O.
    """
    if sys.platform != "win32":
        raise RuntimeError("This sender requires Windows")
    from winrt.windows.devices.enumeration import DeviceInformation, DevicePairingProtectionLevel
    from winrt.windows.devices.bluetooth.genericattributeprofile import GattProtectionLevel

    requester = getattr(getattr(client, "_backend", None), "_requester", None)
    if requester is None:
        raise RuntimeError("Windows device information unavailable")
    info = await DeviceInformation.create_from_id_async(requester.device_information.id)
    if not info.pairing.is_paired or info.pairing.protection_level != DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION:
        raise RuntimeError("Authenticated Windows pairing required")
    await request_windows_service_access(client)
    for uuid in (WRITE_UUID, STATUS_UUID):
        characteristic = client.services.get_characteristic(uuid)
        if characteristic is None:
            raise RuntimeError("Required BLE characteristic missing")
        characteristic.obj.protection_level = GattProtectionLevel.ENCRYPTION_AND_AUTHENTICATION_REQUIRED
    # Force a protected round trip before reading any account-derived data.
    status = bytes(await asyncio.wait_for(client.read_gatt_char(STATUS_UUID), timeout=10))
    if len(status) != 3:
        raise RuntimeError("Invalid protected BLE status")


def start_snapshot_source():
    """Start the Bluetooth version's own local collector, independent of Wi-Fi."""
    if str(BLE_ROOT) not in sys.path:
        sys.path.insert(0, str(BLE_ROOT))
    from ble_backend.server import State
    state = State(False, 60)
    threading.Thread(target=state.refresh_forever, daemon=True).start()
    return state


async def run(address, interval=30, once=False):
    from bleak import BleakClient, BleakScanner

    state = None
    delay = 3
    while True:
        try:
            device = await BleakScanner.find_device_by_filter(
                lambda d, a: d.address.casefold() == address.casefold()
                and SERVICE_UUID.casefold() in (s.casefold() for s in a.service_uuids), timeout=12)
            if device is None:
                raise RuntimeError("Configured display not found")
            async with BleakClient(device, pair=False, timeout=30, winrt={"use_cached_services": False}) as client:
                await require_windows_authenticated_pairing(client)
                print("Authenticated display connected.", flush=True)
                if state is None:
                    state = start_snapshot_source()
                delay = 3
                while client.is_connected:
                    with state.lock:
                        snapshot = copy.deepcopy(state.value)
                    payload = make_payload(snapshot)
                    await send_snapshot(client, payload)
                    print("Display snapshot sent.", flush=True)
                    if once:
                        return 0
                    await asyncio.sleep(interval)
            raise RuntimeError("Display disconnected")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # No exception text, addresses, status bodies, PINs or tokens.
            print(f"Display update unavailable ({type(exc).__name__}).", flush=True)
            if once:
                return 1
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


def main():
    parser = argparse.ArgumentParser(description="Experimental authenticated Windows BLE sender")
    parser.add_argument("--address", required=True, help="paired display BLE address")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 5 <= args.interval <= 3600:
        parser.error("interval must be between 5 and 3600 seconds")
    try:
        return asyncio.run(run(args.address, args.interval, args.once))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
