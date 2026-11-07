"""Bluetooth-only local snapshot collector; it does not start an HTTP service."""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta
from .weather import WeatherCache, unavailable


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

