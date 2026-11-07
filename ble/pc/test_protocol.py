import asyncio
import json
import threading
import struct
import unittest
import zlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError

import demo_sender
from local_source import fetch_display_payload, validate_local_url
from protocol import DATA_MAX, FRAME_MAX, MAX_PAYLOAD, STATUS_UUID, WRITE_UUID, frames, make_payload


class FramesTest(unittest.TestCase):
    def test_reassemble_default_mtu_boundaries(self):
        for length in (1, 16, 17, 18, 34, 35, 2048, 4096):
            original = bytes(i % 256 for i in range(length))
            packets = list(frames(original))
            self.assertTrue(all(len(packet) <= FRAME_MAX for packet in packets))
            self.assertEqual(packets[0][0], 1)
            size, checksum = struct.unpack("<HI", packets[0][1:])
            self.assertEqual(size, length)
            self.assertEqual(checksum, zlib.crc32(original))
            pieces = packets[1:-1]
            for i, piece in enumerate(pieces):
                self.assertEqual(piece[0], 2)
                self.assertEqual(struct.unpack("<H", piece[1:3])[0], i)
                self.assertTrue(0 < len(piece[3:]) <= DATA_MAX)
            self.assertEqual(b"".join(piece[3:] for piece in pieces), original)
            self.assertEqual(packets[-1], b"\x03")

    def test_length_bounds(self):
        for invalid in (b"", b"x" * (MAX_PAYLOAD + 1), "not bytes"):
            with self.assertRaises(ValueError):
                list(frames(invalid))

    def test_sanitizes_and_preserves_source_timestamps(self):
        sample = demo_sender.synthetic_snapshot()
        sample["updated_at"] = "2026-10-28T11:20:00+00:00"
        sample["weather"]["updated_at"] = "2026-10-28T11:15:00+00:00"
        sample["secret"] = "private-secret-sentinel"
        sample["weather"]["error"] = "sensitive exception details"
        sample["weather"]["humidity_percent"] = float("nan")
        sample["weather"]["condition"] = ["bad"]
        now = datetime(2026, 10, 28, 11, 30, tzinfo=timezone.utc)
        payload = make_payload(sample, now=now)
        self.assertNotIn(b"private-secret-sentinel", payload)
        self.assertNotIn(b"sensitive exception details", payload)
        data = json.loads(payload)
        self.assertEqual(data["updated_at"], "2026-10-28T11:20:00+00:00")
        self.assertEqual(data["weather"]["updated_at"], "2026-10-28T11:15:00+00:00")
        self.assertEqual(data["host_utc"], "2026-10-28T11:30:00+00:00")
        self.assertEqual(data["weather"]["error"], "unavailable")
        self.assertIsNone(data["weather"]["humidity_percent"])
        self.assertIsNone(data["weather"]["condition"])


class FakeClient:
    def __init__(self, *, reject=False):
        self.writes = []
        self.status = (0, 0)
        self.reject = reject
        self.reads = 0

    async def write_gatt_char(self, characteristic, packet, response):
        assert characteristic == WRITE_UUID and response is True
        self.writes.append(bytes(packet))
        if self.reject:
            self.status = (3, 0)
        elif packet[0] == 1:
            self.status = (1, 0)
        elif packet[0] == 2:
            self.status = (1, struct.unpack("<H", packet[1:3])[0] + 1)
        else:
            self.status = (2, self.status[1])

    async def read_gatt_char(self, characteristic):
        assert characteristic == STATUS_UUID
        self.reads += 1
        return struct.pack("<BH", *self.status)


class DelayedAckClient(FakeClient):
    """Emulate the device's asynchronous application callback after ATT ACK."""
    def __init__(self):
        super().__init__()
        self.previous = (0, 0)
        self.pending = False
        self.polls = 0

    async def write_gatt_char(self, characteristic, packet, response):
        # The next frame must never be written before the previous ACK was read.
        assert not self.pending
        self.previous = self.status
        await super().write_gatt_char(characteristic, packet, response)
        self.pending = True
        self.polls = 0

    async def read_gatt_char(self, characteristic):
        assert characteristic == STATUS_UUID
        self.reads += 1
        self.polls += 1
        if self.polls < 3:
            return struct.pack("<BH", *self.previous)
        self.pending = False
        return struct.pack("<BH", *self.status)


class SendTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_write_waits_for_application_ack(self):
        client = FakeClient()
        payload = b"hello" * 20
        await demo_sender.send_snapshot(client, payload)
        self.assertEqual(len(client.writes), len(list(frames(payload))))
        self.assertEqual(client.reads, len(client.writes))

    async def test_rejection_stops_sending(self):
        client = FakeClient(reject=True)
        with self.assertRaises(RuntimeError):
            await demo_sender.send_snapshot(client, b"hello" * 20)
        self.assertEqual(len(client.writes), 1)

    async def test_waits_through_stale_status_before_each_next_frame(self):
        client = DelayedAckClient()
        await demo_sender.send_snapshot(client, b"synthetic payload")
        self.assertFalse(client.pending)
        self.assertEqual(client.reads, len(client.writes) * 3)


class LocalSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer synthetic-token":
                    self.send_response(401)
                    self.end_headers()
                    return
                sample = demo_sender.synthetic_snapshot()
                sample["private_field"] = "synthetic-secret"
                body = json.dumps(sample).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.worker.start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}/api/status"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join(timeout=2)

    def test_authenticated_mock_source_and_whitelist(self):
        payload = fetch_display_payload(self.url, "synthetic-token")
        self.assertEqual(json.loads(payload)["mode"], "mock")
        self.assertNotIn(b"synthetic-secret", payload)
        with self.assertRaises(HTTPError):
            fetch_display_payload(self.url, "invalid")

    def test_rejects_nonlocal_or_ambiguous_sources(self):
        for bad in ("http://192.0.2.1/api/status", "http://example.com/api/status",
                    "http://127.0.0.1/api/status?token=bad", "http://u:p@127.0.0.1/api/status"):
            with self.assertRaises(ValueError):
                validate_local_url(bad)


if __name__ == "__main__":
    unittest.main()
