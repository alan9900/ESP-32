import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import threading

import live_sender
import demo_sender


class WindowsSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_windows_service_access_and_gatt_protection(self):
        from winrt.windows.devices.enumeration import DeviceAccessStatus
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattProtectionLevel
        characteristics = {uuid: SimpleNamespace(obj=SimpleNamespace(protection_level=None))
                           for uuid in (live_sender.WRITE_UUID, live_sender.STATUS_UUID)}
        request = AsyncMock(return_value=DeviceAccessStatus.ALLOWED)
        client = SimpleNamespace(services=SimpleNamespace(
            get_service=lambda _: SimpleNamespace(obj=SimpleNamespace(request_access_async=request)),
            get_characteristic=characteristics.get))
        await demo_sender.request_windows_service_access(client)
        for item in characteristics.values():
            self.assertEqual(item.obj.protection_level, GattProtectionLevel.ENCRYPTION_AND_AUTHENTICATION_REQUIRED)
        request.return_value = DeviceAccessStatus.DENIED_BY_USER
        with self.assertRaises(RuntimeError):
            await demo_sender.request_windows_service_access(client)

    async def test_security_gate_enforces_pairing_and_protected_characteristics(self):
        from winrt.windows.devices.enumeration import DevicePairingProtectionLevel
        from winrt.windows.devices.bluetooth.genericattributeprofile import GattProtectionLevel

        characteristics = {uuid: SimpleNamespace(obj=SimpleNamespace(protection_level=None))
                           for uuid in (live_sender.WRITE_UUID, live_sender.STATUS_UUID)}
        client = SimpleNamespace(
            _backend=SimpleNamespace(_requester=SimpleNamespace(device_information=SimpleNamespace(id="test"))),
            services=SimpleNamespace(get_characteristic=characteristics.get),
            read_gatt_char=AsyncMock(return_value=b"\x00\x00\x00"),
        )
        pairing = SimpleNamespace(is_paired=True, protection_level=DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION)
        information = SimpleNamespace(create_from_id_async=AsyncMock(return_value=SimpleNamespace(pairing=pairing)))
        with patch("winrt.windows.devices.enumeration.DeviceInformation", information), \
             patch("live_sender.request_windows_service_access", new_callable=AsyncMock) as access:
            await live_sender.require_windows_authenticated_pairing(client)
            access.assert_awaited_once_with(client)
            for characteristic in characteristics.values():
                self.assertEqual(characteristic.obj.protection_level, GattProtectionLevel.ENCRYPTION_AND_AUTHENTICATION_REQUIRED)
            client.read_gatt_char.assert_awaited_once()

            # Windows may regard an encrypted Just Works bond as paired; reject it.
            pairing.protection_level = DevicePairingProtectionLevel.ENCRYPTION
            client.read_gatt_char.reset_mock()
            with self.assertRaises(RuntimeError):
                await live_sender.require_windows_authenticated_pairing(client)
            client.read_gatt_char.assert_not_awaited()

    async def test_no_live_data_read_if_security_gate_fails(self):
        fake = SimpleNamespace(is_connected=True)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=fake)
        context.__aexit__ = AsyncMock(return_value=False)
        scanner = SimpleNamespace(find_device_by_filter=AsyncMock(return_value=object()))
        with patch("bleak.BleakScanner", scanner), patch("bleak.BleakClient", return_value=context), \
             patch("live_sender.require_windows_authenticated_pairing", AsyncMock(side_effect=RuntimeError)), \
             patch("live_sender.start_snapshot_source") as source, patch("live_sender.send_snapshot", new_callable=AsyncMock) as send:
            self.assertEqual(await live_sender.run("00:11:22:33:44:55", once=True), 1)
            source.assert_not_called()
            send.assert_not_awaited()

    async def test_authenticated_sender_uses_independent_source(self):
        fake = SimpleNamespace(is_connected=True)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=fake)
        context.__aexit__ = AsyncMock(return_value=False)
        scanner = SimpleNamespace(find_device_by_filter=AsyncMock(return_value=object()))
        state = SimpleNamespace(lock=threading.Lock(), value=demo_sender.synthetic_snapshot())
        with patch("bleak.BleakScanner", scanner), patch("bleak.BleakClient", return_value=context), \
             patch("live_sender.require_windows_authenticated_pairing", new_callable=AsyncMock), \
             patch("live_sender.start_snapshot_source", return_value=state) as source, \
             patch("live_sender.send_snapshot", new_callable=AsyncMock) as send:
            self.assertEqual(await live_sender.run("00:11:22:33:44:55", once=True), 0)
            source.assert_called_once()
            send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
