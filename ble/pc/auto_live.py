"""Select one nearby BLE display, then run the authenticated live sender.

No account data is collected before live_sender validates Windows pairing,
authenticated GATT protection and a protected status read. Only one matching
display is accepted; discovery is not itself an identity or security check.
"""
from __future__ import annotations

import asyncio

from bleak import BleakScanner

from live_sender import run
from protocol import SERVICE_UUID


async def main():
    while True:
        try:
            found = await BleakScanner.discover(timeout=12, return_adv=True)
            displays = [device for device, advertisement in found.values()
                        if SERVICE_UUID.casefold() in
                        (uuid.casefold() for uuid in advertisement.service_uuids)]
            if len(displays) != 1:
                raise RuntimeError("Expected exactly one display")
            return await run(displays[0].address)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Display discovery unavailable ({type(exc).__name__}).", flush=True)
            await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
