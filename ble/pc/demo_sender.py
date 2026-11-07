"""Windows BLE proof of concept: synthetic snapshots only, never real account data."""
from __future__ import annotations

import argparse
import asyncio
import struct
import sys
from datetime import datetime, timedelta, timezone

from protocol import SERVICE_UUID, WRITE_UUID, STATUS_UUID, frames, make_payload


async def request_windows_service_access(client):
    """Obtain WinRT service permission before using any GATT characteristic."""
    if sys.platform != "win32":
        raise RuntimeError("This test requires Windows")
    from winrt.windows.devices.enumeration import DeviceAccessStatus
    from winrt.windows.devices.bluetooth.genericattributeprofile import GattProtectionLevel
    service = client.services.get_service(SERVICE_UUID)
    if service is None:
        raise RuntimeError("BLE service missing")
    access = await asyncio.wait_for(service.obj.request_access_async(), timeout=10)
    if access != DeviceAccessStatus.ALLOWED:
        raise RuntimeError("Windows denied BLE service access")
    for uuid in (WRITE_UUID, STATUS_UUID):
        characteristic = client.services.get_characteristic(uuid)
        if characteristic is None:
            raise RuntimeError("BLE characteristic missing")
        characteristic.obj.protection_level = GattProtectionLevel.ENCRYPTION_AND_AUTHENTICATION_REQUIRED


def synthetic_snapshot():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = now.isoformat()
    return {
        "mode": "mock", "updated_at": stamp,
        "codex": {
            "five_hour": {"remaining_percent": 72, "resets_at": (now + timedelta(hours=2)).isoformat()},
            "weekly": {"remaining_percent": 43, "resets_at": (now + timedelta(days=4)).isoformat()},
            "error": None,
        },
        "weather": {"city": "Changsha", "condition": "Clear", "temperature_c": 24,
                    "humidity_percent": 68, "high_c": 27, "low_c": 19,
                    "forecast_date": now.astimezone(timezone(timedelta(hours=8))).date().isoformat(),
                    "updated_at": stamp, "error": None},
    }


async def send_snapshot(client, payload):
    """Wait for an application ACK after every write; ATT response is insufficient."""
    sequence_count = 0
    for part in frames(payload):
        await asyncio.wait_for(client.write_gatt_char(WRITE_UUID, part, response=True), timeout=10)
        if part[0] == 1:
            expected = (1, 0)
        elif part[0] == 2:
            sequence_count += 1
            expected = (1, sequence_count)
        else:
            expected = (2, sequence_count)
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            status = bytes(await asyncio.wait_for(client.read_gatt_char(STATUS_UUID), timeout=3))
            if len(status) != 3:
                raise RuntimeError("Invalid BLE status")
            state, next_sequence = struct.unpack("<BH", status)
            if state == 3:
                raise RuntimeError("Device rejected the payload")
            if (state, next_sequence) == expected:
                break
            await asyncio.sleep(0.05)
        else:
            raise TimeoutError("Device ACK timeout")


async def run(args):
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError:
        print("BLE dependency not installed; see README.")
        return 2
    delay = 3
    while True:
        try:
            print("Scanning for the test BLE service...", flush=True)
            device = await BleakScanner.find_device_by_filter(
                lambda d, a: SERVICE_UUID.lower() in (s.lower() for s in a.service_uuids)
                and (not args.address or d.address.lower() == args.address.lower()), timeout=12)
            if device is None:
                raise RuntimeError("Test device not found")
            print("Test device found. Pair using Windows Settings and the board's PIN first.", flush=True)
            # Bleak's WinRT pair() currently implements CONFIRM_ONLY, not a
            # PIN-entry ceremony. Use the OS pairing UI instead of asking it
            # to silently downgrade the board's authenticated pairing.
            # Windows can retain stale GATT handles after reflashing; force a
            # fresh service/characteristic discovery on every connection.
            async with BleakClient(device, pair=False, timeout=90, winrt={"use_cached_services": False}) as client:
                await request_windows_service_access(client)
                print("Connected. Sending only synthetic test data.", flush=True)
                delay = 3
                while client.is_connected:
                    await send_snapshot(client, make_payload(synthetic_snapshot()))
                    print("Synthetic snapshot accepted.", flush=True)
                    if args.once:
                        return 0
                    await asyncio.sleep(args.interval)
            raise RuntimeError("Disconnected")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Do not print payloads, secrets, addresses or exception text.
            print(f"BLE test unavailable ({type(exc).__name__}); reconnecting.", flush=True)
            if args.once:
                return 1
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


def main():
    parser = argparse.ArgumentParser(description="BLE test sender (synthetic data only)")
    parser.add_argument("--address", default=None, help="target device BLE address, if known")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 5 <= args.interval <= 3600:
        parser.error("interval must be between 5 and 3600 seconds")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("BLE test stopped.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
