"""Helpers for extracting hashes from torrent bytes and magnet links."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

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


def _normalize_btmh(value: str) -> Optional[str]:
    val = value.strip().lower()
    if val.startswith("urn:btmh:"):
        val = val[len("urn:btmh:") :]
    if len(val) == 68 and val.startswith("1220") and _HEX_RE.match(val):
        return val[4:]
    if len(val) == 64 and _HEX_RE.match(val):
        return val
    return None


def normalize_info_hash(value) -> Optional[str]:
    """Normalize v1 btih or v2 btmh hash forms to lowercase hex digest."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) in (20, 32):
            return binascii.hexlify(raw).decode("ascii")
        try:
            value = raw.decode("ascii")
        except Exception:
            value = raw.decode("utf-8", "ignore")

    val = str(value).strip()
    lower = val.lower()
    if lower.startswith("urn:btih:"):
        payload = val[len("urn:btih:") :]
        return _normalize_hex(payload) or _normalize_base32(payload)
    if lower.startswith("urn:btmh:"):
        return _normalize_btmh(val)
    return _normalize_btmh(val) or _normalize_hex(val)


def btmh_from_v2_hash(value) -> Optional[str]:
    v2_hash = normalize_info_hash(value)
    if v2_hash and len(v2_hash) != 64:
        v2_hash = None
    return f"1220{v2_hash}" if v2_hash else None


def build_magnet_from_hashes(v1_hash=None, v2_hash=None, display_name=None, trackers=None) -> str:
    params = []
    v1 = normalize_info_hash(v1_hash)
    if v1 and len(v1) == 40:
        params.append(("xt", f"urn:btih:{v1}"))

    v2 = normalize_info_hash(v2_hash)
    if v2 and len(v2) != 64:
        v2 = None
    if v2:
        params.append(("xt", f"urn:btmh:1220{v2}"))

    if not params:
        return ""
    if display_name:
        params.append(("dn", str(display_name)))
    for tracker in trackers or []:
        if tracker:
            params.append(("tr", str(tracker)))
    return "magnet:?" + urlencode(params)


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
        btih_hash = None
        btmh_hash = None
        for xt in xts:
            if not isinstance(xt, str):
                continue
            lower_xt = xt.lower()
            if lower_xt.startswith("urn:btih:"):
                btih_hash = normalize_info_hash(xt) or btih_hash
            elif lower_xt.startswith("urn:btmh:"):
                btmh_hash = normalize_info_hash(xt) or btmh_hash
        if btih_hash:
            return btih_hash
        if btmh_hash:
            return btmh_hash
    except Exception:
        pass

    if lt:
        try:
            params = lt.parse_magnet_uri(url)
            if params.info_hashes.has_v1():
                return str(params.info_hashes.v1)
            if params.info_hashes.has_v2():
                return str(params.info_hashes.v2)
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
