"""Offline contract tests against the actual C++ receiver, using mock data only.

Set BLE_PROJECT_ALIAS to an ASCII-path directory junction to the project and
BLE_CONTRACT_ZIG to a verified local zig.exe. All build/cache files stay in
the project's .project_storage/work-temp directory. The tests do not use BLE.
"""
import os
from pathlib import Path
import struct
import subprocess
import unittest

import demo_sender
from protocol import frames, make_payload


class ReceiverContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        alias = os.environ.get("BLE_PROJECT_ALIAS")
        compiler = os.environ.get("BLE_CONTRACT_ZIG")
        if not alias or not compiler:
            raise unittest.SkipTest("Set BLE_PROJECT_ALIAS and BLE_CONTRACT_ZIG to run native contract tests")
        root = Path(alias)
        build = root / ".project_storage" / "work-temp" / "ble-contract"
        build.mkdir(parents=True, exist_ok=True)
        cls.exe = build / "frame_contract.exe"
        env = os.environ.copy()
        env["ZIG_GLOBAL_CACHE_DIR"] = str(build / "zig-global-cache")
        env["TEMP"] = env["TMP"] = str(build)
        command = [compiler, "c++", "-std=c++17", "-O2",
                   str(root / "ble" / "firmware" / "src" / "frame_assembler.cpp"),
                   str(root / "ble" / "pc" / "frame_contract.cpp"),
                   "-I", str(root / "ble" / "firmware" / "src"), "-o", str(cls.exe)]
        subprocess.run(command, cwd=build, env=env, check=True, timeout=180,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def run_receiver(self, packets, times=None):
        if times is None:
            times = range(len(packets))
        entries = list(zip(times, packets, strict=True))
        wire = bytearray(struct.pack("<H", len(entries)))
        for timestamp, packet in entries:
            self.assertLessEqual(len(packet), 255)
            wire.extend(struct.pack("<IB", timestamp, len(packet)))
            wire.extend(packet)
        result = subprocess.run([str(self.exe)], input=bytes(wire), check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        size = 3 * len(entries)
        statuses = [struct.unpack_from("<BH", result.stdout, 3 * i) for i in range(len(entries))]
        length = struct.unpack_from("<H", result.stdout, size)[0]
        payload = result.stdout[size + 2:]
        self.assertEqual(len(payload), length)
        return statuses, payload

    def test_real_receiver_reassembles_python_mock_snapshot(self):
        payload = make_payload(demo_sender.synthetic_snapshot())
        packets = list(frames(payload))
        statuses, received = self.run_receiver(packets)
        self.assertEqual(statuses[0], (1, 0))
        self.assertEqual(statuses[-1], (2, len(packets) - 2))
        self.assertEqual(received, payload)

    def test_real_receiver_rejects_corruption_and_sequence_errors(self):
        packets = list(frames(b"synthetic payload for CRC check"))
        corrupt = list(packets)
        corrupt[1] = corrupt[1][:-1] + bytes([corrupt[1][-1] ^ 1])
        statuses, _ = self.run_receiver(corrupt)
        self.assertEqual(statuses[-1][0], 3)
        duplicate = [packets[0], packets[1], packets[1]]
        statuses, _ = self.run_receiver(duplicate)
        self.assertEqual(statuses[-1][0], 3)

    def test_real_receiver_rejects_timeout_and_oversize_frame(self):
        packets = list(frames(b"synthetic"))
        statuses, _ = self.run_receiver(packets[:2], times=[0, 10001])
        self.assertEqual(statuses[-1][0], 3)
        statuses, _ = self.run_receiver([bytes(21)])
        self.assertEqual(statuses[-1][0], 3)


if __name__ == "__main__":
    unittest.main()
