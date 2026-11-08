#!/usr/bin/env python3
"""Claude Code PreToolUse hook: refuse WebFetch to non-public addresses.

Listing pages are untrusted input; a page could try to make Claude fetch
URLs on the local network (My Home, Home Assistant, cloud metadata...).
Exit code 2 blocks the tool call and shows stderr to Claude.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import sys
from typing import Callable
from urllib.parse import urlsplit


def _resolve(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except (socket.gaierror, UnicodeError, OSError):
        return []


def _is_public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast


def is_blocked(url: str, resolve: Callable[[str], list[str]] = _resolve) -> bool:
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return True
    if parts.scheme not in ("http", "https") or not host:
        return True
    try:
        return not _is_public(str(ipaddress.ip_address(host)))
    except ValueError:
        pass
    if host == "localhost" or host.endswith((".local", ".localhost", ".internal", ".lan", ".home.arpa")):
        return True
    addrs = resolve(host)
    return not addrs or not all(_is_public(a) for a in addrs)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if event.get("tool_name") != "WebFetch":
        return 0
    url = str((event.get("tool_input") or {}).get("url") or "")
    if is_blocked(url):
        print(f"Blocked: {url!r} is not a public internet address (private, local or unresolvable). "
              "Only fetch public listing sites.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
