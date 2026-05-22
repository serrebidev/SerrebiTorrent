"""Helpers for extracting hashes from torrent bytes and magnet links."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from libtorrent_env import prepare_libtorrent_dlls

prepare_libtorrent_dlls()

try:
    import libtorrent as lt
except Exception:
    lt = None


_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_BASE32_RE = re.compile(r"^[A-Z2-7]+=*$", re.IGNORECASE)


def _normalize_hex(value: str) -> Optional[str]:
    val = value.strip()
    if len(val) in (40, 64) and _HEX_RE.match(val):
        return val.lower()
    return None


def _normalize_base32(value: str) -> Optional[str]:
    val = value.strip().upper()
    if not val or not _BASE32_RE.match(val):
        return None
    padding = "=" * ((8 - (len(val) % 8)) % 8)
    try:
        raw = base64.b32decode(val + padding, casefold=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) not in (20, 32):
        return None
    return binascii.hexlify(raw).decode("ascii")


def parse_magnet_infohash(url: str) -> Optional[str]:
    """Return a lowercase hex infohash from a magnet link, if present."""
    if not url:
        return None

    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        xts = []
        for key, values in qs.items():
            if key.lower() == "xt":
                xts.extend(values)
        for xt in xts:
            if not isinstance(xt, str):
                continue
            lower_xt = xt.lower()
            if lower_xt.startswith("urn:btih:"):
                value = xt[len("urn:btih:") :]
                as_hex = _normalize_hex(value)
                if as_hex:
                    return as_hex
                as_b32 = _normalize_base32(value)
                if as_b32:
                    return as_b32
    except Exception:
        pass

    if lt:
        try:
            params = lt.parse_magnet_uri(url)
            if params.info_hashes.has_v1():
                return str(params.info_hashes.v1)
        except Exception:
            pass
    return None


def safe_torrent_info_hash(data: bytes) -> Optional[str]:
    """Return the info hash for torrent bytes, or None when parsing fails."""
    if not lt:
        return None
    try:
        info = lt.torrent_info(data)
        if hasattr(info, "info_hashes"):
            hashes = info.info_hashes()
            if hashes.has_v1():
                return str(hashes.v1)
            if hashes.has_v2():
                return str(hashes.v2)
        return str(info.info_hash())
    except Exception:
        return None
