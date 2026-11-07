"""Local-only source adapter. Not used by the synthetic BLE demo sender."""
from __future__ import annotations

import ipaddress
import json
import socket
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from protocol import make_payload

MAX_SOURCE_BYTES = 16384


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "redirect rejected", headers, fp)


def validate_local_url(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        _ = parsed.port
    except ValueError:
        raise ValueError("Invalid source URL") from None
    if (parsed.scheme not in ("http", "https") or not host or parsed.username is not None or
            parsed.password is not None or parsed.path != "/api/status" or parsed.query or parsed.fragment):
        raise ValueError("Invalid source URL")
    if host == "localhost":
        return url
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("Source must be localhost or this computer's numeric IP") from None
    if not address.is_loopback:
        try:
            local = {ipaddress.ip_address(v[4][0].split("%", 1)[0])
                     for v in socket.getaddrinfo(socket.gethostname(), None)}
        except (OSError, ValueError):
            raise ValueError("Cannot verify local address") from None
        if address not in local:
            raise ValueError("Source address does not belong to this computer")
    return url


def fetch_display_payload(url, token, *, now=None, opener=None):
    """Fetch a bounded local snapshot and drop every field outside the whitelist.

    The caller supplies the local token privately; no credential is printed or
    stored. Do not call this with real data until BLE authentication is verified.
    """
    validate_local_url(url)
    if not isinstance(token, str) or not token:
        raise ValueError("Missing local token")
    opener = opener or build_opener(ProxyHandler({}), NoRedirect())
    req = Request(url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    with opener.open(req, timeout=5) as response:
        raw = response.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Source response too large")
    try:
        obj = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Invalid source response") from None
    return make_payload(obj, now=now)
