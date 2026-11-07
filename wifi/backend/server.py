"""Local status bridge for the desk display. Never sends credentials to the board."""
from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from weather import WeatherCache, unavailable

ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def mock_status():
    now = datetime.now(timezone.utc)
    return {"mode": "mock", "updated_at": iso_now(),
            "codex": {"five_hour": {"remaining_percent": 72, "resets_at": (now + timedelta(hours=2)).isoformat(timespec="seconds")},
                      "weekly": {"remaining_percent": 43, "resets_at": (now + timedelta(days=4)).isoformat(timespec="seconds")}, "error": None},
            "weather": {"city": "Changsha", "condition": "Clear", "temperature_c": 24.0,
                        "humidity_percent": 68, "high_c": 27, "low_c": 19,
                        "forecast_date": now.astimezone(timezone(timedelta(hours=8))).date().isoformat(),
                        "updated_at": now.isoformat(timespec="seconds"), "error": None}}


def empty_window():
    return {"remaining_percent": None, "resets_at": None}


def parse_limits(result):
    # Select the explicitly named Codex bucket. Never substitute an unrelated limit.
    by_id = result.get("rateLimitsByLimitId") or {}
    bucket = by_id.get("codex") or result.get("rateLimits") or {}
    if bucket.get("limitId") not in (None, "codex"):
        return empty_window(), empty_window()
    found = {}
    for name in ("primary", "secondary"):
        window = bucket.get(name) or {}
        mins = window.get("windowDurationMins")
        percent = window.get("usedPercent")
        stamp = window.get("resetsAt")
        if mins not in (300, 10080) or isinstance(percent, bool) or not isinstance(percent, (int, float)):
            continue
        reset = None
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            try:
                reset = datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="seconds")
            except (ValueError, OSError, OverflowError):
                pass
        found[mins] = {"remaining_percent": round(max(0, min(100, 100 - percent)), 2), "resets_at": reset}
    return found.get(300, empty_window()), found.get(10080, empty_window())


def read_codex(timeout=15):
    exe = os.environ.get("DESK_CODEX_EXE") or shutil.which("codex")
    if not exe:
        raise RuntimeError("Codex CLI not found; set DESK_CODEX_EXE")
    # The child owns its auth state. Credentials are neither parsed nor logged here.
    process = subprocess.Popen([exe, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                               bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    messages = queue.Queue()
    def reader():
        try:
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            messages.put(None)
    threading.Thread(target=reader, daemon=True).start()
    def send(obj):
        process.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
        process.stdin.flush()
    def receive(request_id):
        end = time.monotonic() + timeout
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Codex app-server timed out")
            try:
                msg = messages.get(timeout=remaining)
            except queue.Empty:
                raise RuntimeError("Codex app-server timed out") from None
            if msg is None:
                raise RuntimeError("Codex app-server exited")
            if msg.get("id") == request_id:
                if "error" in msg:
                    raise RuntimeError("Codex app-server rejected rate-limit request")
                return msg.get("result") or {}
    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "desk_usage_display", "title": "Desk Usage Display", "version": "0.1.0"}}})
        receive(1)
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "account/rateLimits/read"})
        return parse_limits(receive(2))
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for stream in (process.stdin, process.stdout):
            if stream:
                stream.close()


def live_status(weather_cache=None):
    result = {"mode": "live", "updated_at": iso_now(),
              "codex": {"five_hour": empty_window(), "weekly": empty_window(), "error": None},
              "weather": unavailable(message="Refreshing")}
    try:
        five, weekly = read_codex()
        result["codex"].update(five_hour=five, weekly=weekly)
        if five["remaining_percent"] is None or weekly["remaining_percent"] is None:
            result["codex"]["error"] = "One or more Codex quota windows unavailable"
    except Exception as exc:
        result["codex"]["error"] = str(exc) if isinstance(exc, RuntimeError) else "Codex read failed"
    try:
        result["weather"] = (weather_cache or WeatherCache()).get()
    except Exception:
        result["weather"] = unavailable(message="Weather unavailable")
    result["updated_at"] = iso_now()
    return result


class State:
    def __init__(self, mock, interval):
        self.mock, self.interval = mock, interval
        self.weather_cache = WeatherCache()
        self.lock = threading.Lock()
        self.value = mock_status() if mock else {"mode": "live", "updated_at": iso_now(),
            "codex": {"five_hour": empty_window(), "weekly": empty_window(), "error": "Refreshing"},
            "weather": unavailable(message="Refreshing")}

    def refresh_forever(self):
        while True:
            data = mock_status() if self.mock else live_status(self.weather_cache)
            with self.lock:
                self.value = data
            time.sleep(self.interval)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # No headers or paths in logs (paths can be user supplied).
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            expected = self.server.access_token
            if expected and not hmac.compare_digest(self.headers.get("Authorization", "").encode("utf-8"), ("Bearer " + expected).encode("utf-8")):
                self.send_response(401)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            with self.server.state.lock:
                body = json.dumps(self.server.state.value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (SIMULATOR / relative).resolve()
        if not target.is_relative_to(SIMULATOR.resolve()) or not target.is_file():
            self.send_error(404)
            return
        content_types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}
        if target.suffix.lower() not in content_types:
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_types[target.suffix.lower()])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Local display bridge (mock by default)")
    parser.add_argument("--live", action="store_true", help="query real Codex and weather data")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (LAN binding requires DESK_ACCESS_TOKEN)")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--interval", type=int, default=60, help="refresh interval in seconds, minimum 15")
    args = parser.parse_args()
    token = os.environ.get("DESK_ACCESS_TOKEN", "")
    if args.host not in ("127.0.0.1", "::1", "localhost") and not token:
        parser.error("LAN binding requires DESK_ACCESS_TOKEN environment variable")
    state = State(not args.live, max(15, args.interval))
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.state, server.access_token = state, token
    threading.Thread(target=state.refresh_forever, daemon=True).start()
    print(f"Display bridge listening on http://{args.host}:{args.port}/ ({'LIVE' if args.live else 'MOCK'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
