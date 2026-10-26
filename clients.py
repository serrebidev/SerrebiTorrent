# ruff: noqa: E402

import abc
import binascii
import ipaddress
import os
import re
import socket
import shutil
import time
import threading
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests
import urllib3
from torrent_parsing import (
    build_magnet_from_hashes,
    clean_tracker_urls,
    parse_magnet_infohash,
    torrent_file_magnet,
    torrent_file_storage,
)

MAX_TORRENT_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_TORRENT_URL_REDIRECTS = 5


class BatchRemoveError(RuntimeError):
    def __init__(self, succeeded, failed, message=None):
        self.succeeded = int(succeeded)
        self.failed = int(failed)
        super().__init__(
            message
            or f"Failed to remove one or more torrents ({self.succeeded} removed, {self.failed} failed)."
        )
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _quote_path_preserving_escapes(path):
    parts = []
    pos = 0
    for match in _PERCENT_ESCAPE_RE.finditer(path):
        parts.append(quote(path[pos:match.start()], safe='/:@'))
        parts.append(match.group(0))
        pos = match.end()
    parts.append(quote(path[pos:], safe='/:@'))
    return "".join(parts)


def safe_encode_url(url):
    """Encode special characters (like brackets) in URL path for requests compatibility."""
    parsed = urlparse(url)
    encoded_path = _quote_path_preserving_escapes(parsed.path)
    return urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))


def _is_blocked_torrent_ip(ip):
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def _resolve_torrent_host(host, port):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Torrent URL host could not be resolved.") from exc
    addresses = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except (IndexError, ValueError):
            continue
    if not addresses:
        raise ValueError("Torrent URL host did not resolve to an IP address.")
    return tuple(addresses)


def validate_public_torrent_url(url):
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("Torrent URL must use http or https.")
    host = parsed.hostname
    if not host:
        raise ValueError("Torrent URL host is required.")
    host_check = host.rstrip(".").lower()
    if host_check == "localhost" or host_check.endswith(".localhost"):
        raise ValueError("Localhost torrent URLs are not allowed.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Torrent URL port is invalid.") from exc
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80
    try:
        addresses = (ipaddress.ip_address(host_check),)
    except ValueError:
        addresses = _resolve_torrent_host(host_check, port)
    if any(_is_blocked_torrent_ip(ip) for ip in addresses):
        raise ValueError("Private or local network torrent URLs are not allowed.")
    return parsed


class _PublicPeerMixin:
    # Checked on the connected socket, not a second DNS lookup, so a rebinding
    # name cannot validate as public and then connect somewhere local. Runs at
    # connect time because urllib3 returns empty-body responses (most redirects)
    # to the pool before requests hands them back.
    def _new_conn(self):
        sock = super()._new_conn()
        # ponytail: through a proxy the proxy resolves the host, so only the pre-request DNS check applies.
        if self.proxy:
            return sock
        try:
            peer = ipaddress.ip_address(sock.getpeername()[0])
        except (OSError, ValueError, IndexError, TypeError) as exc:
            sock.close()
            raise ValueError("Torrent connection peer address could not be verified.") from exc
        if _is_blocked_torrent_ip(peer):
            sock.close()
            raise ValueError("Torrent connection reached a private or local network address.")
        return sock


class _PublicHTTPConnection(_PublicPeerMixin, urllib3.connection.HTTPConnection):
    pass


class _PublicHTTPSConnection(_PublicPeerMixin, urllib3.connection.HTTPSConnection):
    pass


class _PublicHTTPPool(urllib3.HTTPConnectionPool):
    ConnectionCls = _PublicHTTPConnection


class _PublicHTTPSPool(urllib3.HTTPSConnectionPool):
    ConnectionCls = _PublicHTTPSConnection


class _PublicPeerAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _PublicHTTPPool, "https": _PublicHTTPSPool}


def _public_torrent_session():
    session = requests.Session()
    adapter = _PublicPeerAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def download_torrent_url(url, timeout=30):
    current = url
    for _ in range(MAX_TORRENT_URL_REDIRECTS + 1):
        validate_public_torrent_url(current)
        content = bytearray()
        with _public_torrent_session() as session, session.get(
            safe_encode_url(current), timeout=timeout, stream=True, allow_redirects=False
        ) as r:
            if r.status_code in _REDIRECT_STATUSES:
                location = r.headers.get("Location")
                if not location:
                    raise ValueError("Torrent URL redirect missing Location header.")
                current = urljoin(current, location)
                continue
            r.raise_for_status()
            content_length = r.headers.get("Content-Length")
            if content_length:
                try:
                    expected_size = int(content_length)
                except ValueError as exc:
                    raise ValueError("Torrent download returned an invalid Content-Length.") from exc
                if expected_size < 0:
                    raise ValueError("Torrent download returned an invalid Content-Length.")
                if expected_size > MAX_TORRENT_DOWNLOAD_BYTES:
                    raise ValueError("Torrent download exceeds 64 MB limit.")
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > MAX_TORRENT_DOWNLOAD_BYTES:
                    raise ValueError("Torrent download exceeds 64 MB limit.")
        return bytes(content)
    raise ValueError("Torrent URL redirected too many times.")


from libtorrent_env import prepare_libtorrent_dlls

def _safe_tracker_domain(tracker_url):
    if not tracker_url:
        return ""
    try:
        return urlparse(tracker_url).hostname or ""
    except Exception:
        return ""


def _torrent_state_value(name):
    """Resolve a torrent_status state name to its enum value or None.

    libtorrent 2.1 moved the state enum to ``torrent_status.states`` and
    dropped members (``queued_for_checking``, ``allocating``) that 2.0 kept
    on ``torrent_status`` itself; ``queued_for_checking`` merged into
    ``checking_resume_data``.
    """
    states = getattr(lt.torrent_status, "states", None)
    if states is not None:
        try:
            return int(getattr(states, name))
        except (AttributeError, TypeError, ValueError):
            pass
    try:
        return int(getattr(lt.torrent_status, name))
    except (AttributeError, TypeError, ValueError):
        return None


def _torrent_status_flag(status, name):
    """Boolean flag from a torrent_status object, across libtorrent versions.

    libtorrent 2.1 removed the ``paused``/``auto_managed`` attributes from
    ``torrent_status``; the same facts now live in the ``torrent_flags``
    bitmask exposed as ``status.flags``. Prefer the legacy attribute when the
    running libtorrent still exposes it (2.0) and fall back to the bitmask,
    so one code path serves both.
    """
    try:
        return bool(getattr(status, name))
    except AttributeError:
        pass
    try:
        flags = getattr(status, "flags", 0)
        flags_t = getattr(lt, "torrent_flags", None)
        if flags_t is None:
            return False
        bit = getattr(flags_t, name, 0)
        return bool(bit) and bool(flags & bit)
    except Exception:
        return False


def _handle_has_metadata(handle):
    """Whether a handle has metadata, across libtorrent versions.

    libtorrent 2.1 removed ``torrent_handle.has_metadata()``; the fact now
    lives on ``torrent_status.has_metadata``.
    """
    try:
        return bool(handle.has_metadata())
    except AttributeError:
        pass
    try:
        return bool(handle.status().has_metadata)
    except Exception:
        return False


def _handle_torrent_info(handle):
    """The handle's torrent_info, or None, across libtorrent versions.

    libtorrent 2.1 removed ``torrent_handle.get_torrent_info()`` in favor of
    ``torrent_file()``.
    """
    try:
        return handle.get_torrent_info()
    except AttributeError:
        pass
    try:
        return handle.torrent_file()
    except Exception:
        return None


def _handle_file_priorities(handle):
    """The handle's file priority list, across libtorrent versions.

    libtorrent 2.1 renamed ``torrent_handle.file_priorities()`` to
    ``get_file_priorities()``.
    """
    try:
        return handle.file_priorities()
    except AttributeError:
        pass
    return handle.get_file_priorities()


def _handle_set_auto_managed(handle, enabled):
    """Set or clear a handle's auto-managed flag across libtorrent versions.

    libtorrent 2.1 removed ``torrent_handle.auto_managed(bool)``; the flag
    now lives in the ``torrent_flags`` bitmask. A manual pause must clear it
    so the queue manager cannot restart the torrent and the GUI reports it
    as stopped.
    """
    try:
        handle.auto_managed(enabled)
        return
    except AttributeError:
        pass
    try:
        flags_t = getattr(lt, "torrent_flags", None)
        if flags_t is None:
            return
        if enabled:
            handle.set_flags(flags_t.auto_managed, flags_t.auto_managed)
        else:
            handle.unset_flags(flags_t.auto_managed)
    except Exception:
        pass

class BaseClient(abc.ABC):
    handles_magnet_start = True
    supports_queue_reordering = False
    supports_move_storage = False
    supports_torrent_rate_limits = False
    supports_free_space_query = False
    _magnet_add_lock = threading.RLock()
    _torrent_file_add_lock = threading.RLock()

    def add_magnet(self, url, save_path, start):
        with self._magnet_add_lock:
            duplicate = self.find_magnet_duplicate(url)
            if duplicate:
                return duplicate
            self._add_new_magnet(url, save_path, start)
        return None

    def _add_new_magnet(self, url, save_path, start):
        self.add_torrent_url(url, save_path)

    def add_torrent_file_if_new(self, data, save_path=None, priorities=None, before_add=None):
        """Avoid duplicate torrent-file adds within this process."""
        magnet = torrent_file_magnet(data)
        with self._torrent_file_add_lock:
            duplicate = self.find_magnet_duplicate(magnet) if magnet else None
            if duplicate:
                return magnet, duplicate
            if before_add is not None:
                before_add()
            self.add_torrent_file(data, save_path, priorities)
        return magnet, None

    def add_trackers(self, info_hash, trackers):
        raise NotImplementedError

    @abc.abstractmethod
    def test_connection(self):
        pass

    @abc.abstractmethod
    def get_torrents_full(self):
        pass
    
    @abc.abstractmethod
    def start_torrent(self, h):
        pass

    @abc.abstractmethod
    def stop_torrent(self, h):
        pass

    def queue_up(self, h):
        raise NotImplementedError("Torrent queue reordering is not supported by this client.")

    def queue_down(self, h):
        raise NotImplementedError("Torrent queue reordering is not supported by this client.")

    def queue_top(self, h):
        raise NotImplementedError("Torrent queue reordering is not supported by this client.")

    def queue_bottom(self, h):
        raise NotImplementedError("Torrent queue reordering is not supported by this client.")

    def move_torrent_data(self, h, destination):
        raise NotImplementedError("Moving torrent data is not supported by this client.")

    def set_torrent_rate_limits(self, h, download_limit, upload_limit):
        raise NotImplementedError("Per-torrent rate limits are not supported by this client.")

    def get_free_space(self, path):
        raise NotImplementedError("Free-space queries are not supported by this client.")

    @abc.abstractmethod
    def remove_torrent(self, h):
        pass

    @abc.abstractmethod
    def remove_torrent_with_data(self, h):
        pass

    def remove_torrents(self, hs, df=False):
        hashes = self._normalize_hashes(hs)
        if not hashes:
            return
        delete_files = self._normalize_delete_files(df)
        succeeded = 0
        failed = 0
        for h in hashes:
            if not h:
                continue
            try:
                if delete_files:
                    self.remove_torrent_with_data(h)
                else:
                    self.remove_torrent(h)
                succeeded += 1
            except Exception:
                failed += 1
        if failed:
            raise BatchRemoveError(succeeded, failed)

    def _normalize_hashes(self, hs):
        if hs is None:
            return []
        if isinstance(hs, (str, bytes, bytearray, memoryview)):
            hs = [hs]
        out = []
        for h in hs:
            if h is None:
                continue
            normalized = self._normalize_hash(h)
            if normalized:
                out.append(normalized)
        return out

    def _normalize_hash(self, h):
        if h is None:
            return None
        if isinstance(h, (bytes, bytearray, memoryview)):
            raw = bytes(h)
            if len(raw) == 20:
                return binascii.hexlify(raw).decode("ascii")
            try:
                text = raw.decode("ascii")
            except Exception:
                return raw.decode("utf-8", "ignore").strip()
            text = text.strip()
            if text and all(c in "0123456789abcdefABCDEF" for c in text) and len(text) in (40, 64):
                return text.lower()
            return text
        if hasattr(h, "to_string"):
            try:
                raw = h.to_string()
                if isinstance(raw, (bytes, bytearray, memoryview)):
                    raw_bytes = bytes(raw)
                    if len(raw_bytes) == 20:
                        return binascii.hexlify(raw_bytes).decode("ascii")
                    try:
                        text = raw_bytes.decode("ascii").strip()
                    except Exception:
                        return raw_bytes.decode("utf-8", "ignore").strip()
                    if text and all(c in "0123456789abcdefABCDEF" for c in text) and len(text) in (40, 64):
                        return text.lower()
                    return text
            except Exception:
                pass
        return str(h).strip()

    def _normalize_delete_files(self, delete_files):
        if isinstance(delete_files, bool):
            return delete_files
        if isinstance(delete_files, (int, float)):
            return bool(delete_files)
        if isinstance(delete_files, str):
            value = delete_files.strip().lower()
            if value in ("1", "true", "yes", "y", "on"):
                return True
            if value in ("0", "false", "no", "n", "off", ""):
                return False
        return bool(delete_files)

    @abc.abstractmethod
    def add_torrent_url(self, u, sp=None):
        pass

    @abc.abstractmethod
    def add_torrent_file(self, c, sp=None, p=None):
        pass

    @abc.abstractmethod
    def get_global_stats(self):
        pass

    def get_app_preferences(self):
        return None

    def set_app_preferences(self, p):
        raise NotImplementedError

    def find_magnet_duplicate(self, url):
        return None

    def get_default_save_path(self):
        return None

    def recheck_torrent(self, h):
        raise NotImplementedError

    def reannounce_torrent(self, h):
        raise NotImplementedError

    @abc.abstractmethod
    def get_torrent_save_path(self, h):
        return None

    @abc.abstractmethod
    def get_files(self, h):
        pass

    @abc.abstractmethod
    def set_file_priority(self, h, i, p):
        pass

    @abc.abstractmethod
    def get_peers(self, h):
        pass

    @abc.abstractmethod
    def get_trackers(self, h):
        pass

# --- rTorrent ---
from defusedxml.xmlrpc import monkey_patch as _defusedxml_xmlrpc_monkey_patch

_defusedxml_xmlrpc_monkey_patch()

import xmlrpc.client  # nosec B411
import io
import ssl

class CookieTransport(xmlrpc.client.SafeTransport):
    def __init__(self, c=None, ck=None):
        super().__init__(context=c)
        self.cookies = ck or {}

    def send_user_agent(self, cn):
        if self.cookies:
            cn.putheader("Cookie", "; ".join([f"{k}={v}" for k, v in self.cookies.items()]))
        super().send_user_agent(cn)

SCGI_MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class SCGITransport(xmlrpc.client.Transport):
    def __init__(self, h, p):
        super().__init__()
        self.sh, self.sp = h, p

    def request(self, h, hn, rb, v=False):
        hd = {
            "CONTENT_LENGTH": str(len(rb)),
            "SCGI": "1",
            "REQUEST_METHOD": "POST",
            "REQUEST_URI": hn if hn else "/"
        }
        c = b"".join([k.encode('ascii')+b'\0'+v.encode('ascii')+b'\0' for k,v in hd.items()])
        p = str(len(c)).encode('ascii')+b':'+c+b','+rb
        
        try:
            with socket.create_connection((self.sh, self.sp), timeout=10) as s:
                s.sendall(p)
                rd = bytearray()
                while True:
                    ch = s.recv(4096)
                    if not ch:
                        break
                    rd.extend(ch)
                    if len(rd) > SCGI_MAX_RESPONSE_BYTES:
                        raise RuntimeError("SCGI response exceeds the 64 MB limit.")
                rd = bytes(rd)
        except Exception as e:
            raise xmlrpc.client.ProtocolError(h+hn, 500, str(e), {})

        rs = rd.decode('utf-8', errors='replace')
        if "\r\n\r\n" in rs:
            b = rs.split("\r\n\r\n", 1)[1]
        elif "\n\n" in rs:
            b = rs.split("\n\n", 1)[1]
        else:
            b = rs
        return self.parse_response(io.BytesIO(b.encode('utf-8')))

    def parse_response(self, response_file):
        p, u = self.getparser()
        while True:
            data = response_file.read(1024)
            if not data:
                break
            p.feed(data)
        response_file.close()
        p.close()
        return u.close()

class RTorrentClient(BaseClient):
    def find_magnet_duplicate(self, url):
        info_hash = parse_magnet_infohash(url)
        if not info_hash:
            return None
        for torrent_hash, name in self.srv.d.multicall2("", "main", "d.hash=", "d.name="):
            if str(torrent_hash).lower() == info_hash:
                return torrent_hash, name, [t['url'] for t in self.get_trackers(torrent_hash)]
        return None

    def _add_new_magnet(self, url, save_path, start):
        load = self.srv.load.start if start else self.srv.load.normal
        if save_path:
            load("", url, f"d.directory.set={save_path}")
        else:
            load("", url)

    def add_trackers(self, info_hash, trackers):
        with self._magnet_add_lock:
            current = self.srv.t.multicall(info_hash, "", "t.url=", "t.group=")
            existing = {t[0] for t in current}
            group = min(32, max((int(t[1]) for t in current), default=-1) + 1)
            new = [t for t in clean_tracker_urls(trackers) if t not in existing]
            for tracker in new:
                self.srv.d.tracker.insert(info_hash, group, tracker)
                group = min(32, group + 1)
            if new:
                self.srv.d.save_full_session(info_hash)

    def __init__(self, u, us=None, pw=None):
        if not u.startswith(('http://', 'https://', 'scgi://')):
            u = 'http://' + u
        p = urlparse(u)
        if us and pw is not None and p.scheme != "scgi" and not p.username and p.hostname:
            user = quote(us, safe="")
            password = quote(pw, safe="")
            host = p.hostname
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            port = f":{p.port}" if p.port else ""
            u = p._replace(netloc=f"{user}:{password}@{host}{port}").geturl()
            p = urlparse(u)

        self.u, self.us, self.pw, self.ck, self.tc = u, us, pw, {}, {}
        self.ctx = None
        if p.scheme == "https":
            self.ctx = ssl.create_default_context()
            if os.environ.get("SERREBITORRENT_INSECURE_SSL", "").strip().lower() in ("1", "true", "yes"):
                self.ctx.check_hostname = False
                self.ctx.verify_mode = ssl.CERT_NONE

        if p.scheme == "scgi":
            self.srv = xmlrpc.client.ServerProxy("http://d", transport=SCGITransport(p.hostname, p.port))
        else:
            self.srv = xmlrpc.client.ServerProxy(u, context=self.ctx)

    def _rpc(self, name, *args, default=None, suppress_errors=True):
        try:
            return getattr(self.srv, name)(*args)
        except xmlrpc.client.Fault as e:
            # Re-raise faults as they often contain useful error messages from rTorrent
            print(f"rTorrent RPC Fault in {name}: {e}")
            raise
        except Exception:
            if not suppress_errors:
                raise
            return default

    def test_connection(self):
        return self.srv.system.client_version()

    def _si(self, v):
        if isinstance(v, (list, tuple)) and v:
            return self._si(v[0])
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def _ss(self, v):
        if isinstance(v, (list, tuple)) and v:
            return self._ss(v[0])
        return str(v)

    def get_torrents_full(self):
        try:
            raw = self.srv.d.multicall2("", "main", "d.hash=", "d.bytes_done=", "d.up.total=", "d.ratio=", "d.state=", "d.is_active=", "d.is_hash_checking=", "d.message=", "d.down.rate=", "d.up.rate=", "d.name=", "d.size_bytes=", "d.left_bytes=", "d.connection_seed=", "d.connection_leech=", "d.peers_complete=", "d.peers_accounted=", "d.directory=")
            if not raw:
                return []
            res = []
            for t in raw:
                h, dr, lb = t[0], self._si(t[8]), self._si(t[12])
                res.append({
                    "hash": h, "name": self._ss(t[10]), "size": self._si(t[11]), "done": self._si(t[1]), "up_total": self._si(t[2]), "ratio": self._si(t[3]), "state": self._si(t[4]), "active": self._si(t[5]), "hashing": self._si(t[6]), "message": self._ss(t[7]), "down_rate": dr, "up_rate": self._si(t[9]), "tracker_domain": self.tc.get(h, ""), "save_path": self._ss(t[17]) if len(t)>17 else None, "eta": int(lb/dr) if dr>0 and lb>0 else -1, "seeds_connected": self._si(t[15]), "seeds_total": self._si(t[15]), "leechers_connected": self._si(t[16]), "leechers_total": self._si(t[16])
                })
            return res
        except Exception as e:
            print(f"RTorrent error: {e}")
            raise

    def start_torrent(self, h):
        h = self._normalize_hash(h)
        self.srv.d.open(h)
        self.srv.d.start(h)

    def stop_torrent(self, h):
        h = self._normalize_hash(h)
        self.srv.d.stop(h)
        self.srv.d.close(h)

    def remove_torrent(self, h):
        h = self._normalize_hash(h)
        self.srv.d.erase(h)

    def remove_torrent_with_data(self, h):
        raise NotImplementedError("rTorrent delete-with-data is not supported safely.")

    def add_torrent_url(self, u, sp=None):
        if sp:
            self.srv.load.start("", u, f"d.directory.set={sp}")
        else:
            self.srv.load.start("", u)

    def add_torrent_file(self, c, sp=None, p=None):
        if sp:
            self.srv.load.raw_start("", xmlrpc.client.Binary(c), f"d.directory.set={sp}")
        else:
            self.srv.load.raw_start("", xmlrpc.client.Binary(c))

    def get_global_stats(self):
        return self.srv.throttle.global_down.rate(), self.srv.throttle.global_up.rate()

    def get_app_preferences(self):
        prefs = {
            "dl_limit": self._rpc("throttle.global_down.max_rate"),
            "ul_limit": self._rpc("throttle.global_up.max_rate"),
            "port_range": self._rpc("network.port_range"),
            "dht_mode": self._rpc("dht.mode"),
            "pex_enabled": self._rpc("protocol.pex"),
            "use_udp_trackers": self._rpc("trackers.use_udp"),
            "encryption": self._rpc("protocol.encryption"),
            "proxy_address": self._rpc("network.proxy_address"),
            "max_peers": self._rpc("throttle.max_peers.normal"),
            "min_peers": self._rpc("throttle.min_peers.normal"),
            "max_uploads": self._rpc("throttle.max_uploads"),
            "directory_default": self._rpc("directory.default"),
            "check_hash": self._rpc("pieces.hash.on_completion"),
        }
        res = {k: v for k, v in prefs.items() if v is not None}
        return res if res else None

    def get_default_save_path(self):
        prefs = self.get_app_preferences()
        return prefs.get('directory_default') if prefs else None

    def set_app_preferences(self, p):
        if not p:
            return
        setters = {
            "dl_limit": "throttle.global_down.max_rate.set",
            "ul_limit": "throttle.global_up.max_rate.set",
            "port_range": "network.port_range.set",
            "dht_mode": "dht.mode.set",
            "pex_enabled": "protocol.pex.set",
            "use_udp_trackers": "trackers.use_udp.set",
            "encryption": "protocol.encryption.set",
            "proxy_address": "network.proxy_address.set",
            "max_peers": "throttle.max_peers.normal.set",
            "min_peers": "throttle.min_peers.normal.set",
            "max_uploads": "throttle.max_uploads.set",
            "directory_default": "directory.default.set",
            "check_hash": "pieces.hash.on_completion.set",
        }
        for key, method in setters.items():
            if key not in p:
                continue
            val = p.get(key)
            if val is None:
                continue
            if key in ("pex_enabled", "use_udp_trackers", "check_hash"):
                val = 1 if bool(val) else 0
            self._rpc(method, val, suppress_errors=False)

    def recheck_torrent(self, h):
        h = self._normalize_hash(h)
        self.srv.d.check_hash(h)

    def reannounce_torrent(self, h):
        h = self._normalize_hash(h)
        self.srv.d.tracker_announce(h)

    def get_torrent_save_path(self, h):
        h = self._normalize_hash(h)
        return self.srv.d.directory(h)

    def get_files(self, h):
        h = self._normalize_hash(h)
        r = self.srv.f.multicall(h, "", "f.get_path=", "f.get_size_bytes=", "f.get_priority=", "f.get_completed_chunks=", "f.get_size_chunks=")
        return [{"index": i, "name": x[0], "size": x[1], "progress": x[3]/x[4] if x[4]>0 else 0, "priority": x[2]} for i, x in enumerate(r)]

    def set_file_priority(self, h, i, p):
        h = self._normalize_hash(h)
        self.srv.f.priority.set(h, i, p)
        self.srv.d.update_priorities(h)

    def get_peers(self, h):
        h = self._normalize_hash(h)
        r = self.srv.p.multicall(h, "", "p.address=", "p.client_version=", "p.completed_percent=", "p.down_rate=", "p.up_rate=")
        return [{"address": str(x[0]), "client": str(x[1]), "progress": float(x[2])/100.0, "down_rate": int(x[3]), "up_rate": int(x[4])} for x in r]

    def get_trackers(self, h):
        h = self._normalize_hash(h)
        r = self.srv.t.multicall(h, "", "t.url=", "t.is_enabled=", "t.scrape_complete=")
        return [{"url": str(x[0]), "status": "Enabled" if x[1] else "Disabled", "peers": int(x[2]) if x[2] else 0, "message": ""} for x in r]

# --- qBit ---
import qbittorrentapi
class QBittorrentClient(BaseClient):
    supports_queue_reordering = True
    supports_move_storage = True
    supports_torrent_rate_limits = True
    supports_free_space_query = True
    def find_magnet_duplicate(self, url):
        info_hash = parse_magnet_infohash(url)
        if not info_hash:
            return None
        # qBittorrent identifies pure v2 torrents by their truncated SHA-256 hash.
        candidates = list(dict.fromkeys([info_hash, info_hash[:40]]))
        for torrent in self.c.torrents_info(torrent_hashes=candidates):
            torrent_hash = str(torrent.hash)
            if torrent_hash.lower() in candidates:
                return torrent_hash, torrent.name, [t['url'] for t in self.get_trackers(torrent_hash)]
        return None

    def _add_new_magnet(self, url, save_path, start):
        result = self.c.torrents_add(urls=url, save_path=save_path, is_paused=not start)
        if isinstance(result, str) and result.strip().lower() == "fails.":
            raise RuntimeError("qBittorrent rejected the URL (Fails.)")

    def add_trackers(self, info_hash, trackers):
        with self._magnet_add_lock:
            existing = {t['url'] for t in self.get_trackers(info_hash)}
            new = [t for t in clean_tracker_urls(trackers) if t not in existing]
            if new:
                self.c.torrents_add_trackers(torrent_hash=info_hash, urls=new)

    # qBittorrent acknowledges the delete request before its torrent list is
    # always updated, especially when deleting data on a remote server.
    _DELETE_VERIFY_ATTEMPTS = 20
    _DELETE_VERIFY_DELAY_SECONDS = 0.5

    def __init__(self, u, us, pw):
        if not u.startswith(('http://', 'https://')):
            u = 'http://' + u
        self.c = qbittorrentapi.Client(host=u, username=us, password=pw)
        self.c.auth_log_in()

    def test_connection(self): return self.c.app_version()
    def get_torrents_full(self):
        try:
            ts = self.c.torrents_info()
            res = []
            for t in ts:
                sv, av, hv = 0, 0, 0
                s = str(t.state or "")
                state_key = s.lower()
                if state_key in ['downloading', 'uploading', 'stalleddl', 'stalledup', 'metadl', 'forcedmetadl', 'forceddl', 'forcedup', 'queueddl', 'queuedup']:
                    sv, av = 1, 1
                elif state_key in ['pauseddl', 'pausedup', 'stoppeddl', 'stoppedup']:
                    sv = 0
                elif 'checking' in state_key:
                    hv, sv = 1, 1
                message = ""
                if state_key == "error":
                    message = "Error"
                elif state_key == "missingfiles":
                    message = "Missing files"
                tracker_domain = _safe_tracker_domain(getattr(t, "tracker", "") or "")
                try:
                    queue_position = int(getattr(t, "priority", -1))
                except (TypeError, ValueError):
                    queue_position = -1
                res.append({"hash": t.hash, "name": t.name, "size": t.total_size, "done": t.completed, "up_total": t.uploaded, "ratio": t.ratio * 1000, "state": sv, "active": av, "hashing": hv, "message": message, "down_rate": t.dlspeed, "up_rate": t.upspeed, "tracker_domain": tracker_domain, "eta": int(getattr(t, "eta", -1) or -1), "seeds_connected": int(getattr(t, "num_seeds", 0) or 0), "seeds_total": int(getattr(t, "num_complete", 0) or 0), "leechers_connected": int(getattr(t, "num_leechs", 0) or 0), "leechers_total": int(getattr(t, "num_incomplete", 0) or 0), "availability": getattr(t, "availability", None), "queue_position": queue_position, "save_path": getattr(t, "save_path", None)})
            return res
        except Exception as e:
            print(f"qBittorrent error: {e}")
            raise
    def start_torrent(self, h): self._torrent_action("torrents_start", "torrents_resume", h)
    def stop_torrent(self, h): self._torrent_action("torrents_stop", "torrents_pause", h)
    def queue_up(self, h): self.c.torrents_increase_priority(torrent_hashes=self._normalize_hash(h))
    def queue_down(self, h): self.c.torrents_decrease_priority(torrent_hashes=self._normalize_hash(h))
    def queue_top(self, h): self.c.torrents_top_priority(torrent_hashes=self._normalize_hash(h))
    def queue_bottom(self, h): self.c.torrents_bottom_priority(torrent_hashes=self._normalize_hash(h))
    def move_torrent_data(self, h, destination):
        self.c.torrents_set_location(
            torrent_hashes=self._normalize_hash(h),
            location=destination,
        )
    def set_torrent_rate_limits(self, h, download_limit, upload_limit):
        torrent_hash = self._normalize_hash(h)
        self.c.torrents_set_download_limit(
            limit=int(download_limit) if int(download_limit) > 0 else -1,
            torrent_hashes=torrent_hash,
        )
        self.c.torrents_set_upload_limit(
            limit=int(upload_limit) if int(upload_limit) > 0 else -1,
            torrent_hashes=torrent_hash,
        )
    def remove_torrent(self, h): self.remove_torrents([h], df=False)
    def remove_torrent_with_data(self, h): self.remove_torrents([h], df=True)

    def _torrent_action(self, preferred_method, fallback_method, h):
        torrent_hash = self._normalize_hash(h)
        method = getattr(self.c, preferred_method, None) or getattr(self.c, fallback_method)
        method(torrent_hashes=torrent_hash)

    def remove_torrents(self, hs, df=False):
        hashes = self._normalize_hashes(hs)
        if not hashes:
            return
        existing = self._existing_torrent_hashes(hashes)
        if not existing:
            raise BatchRemoveError(0, len(hashes), "qBittorrent has no matching torrent for the selected hash.")

        to_delete = [h for h in hashes if h.lower() in existing]
        missing = len(hashes) - len(to_delete)
        self.c.torrents_delete(torrent_hashes=to_delete, delete_files=self._normalize_delete_files(df))
        remaining = self._wait_for_removed(to_delete)
        failed = missing + len(remaining)
        if failed:
            succeeded = len(to_delete) - len(remaining)
            sample = ", ".join(sorted(remaining)[:3])
            extra = "" if len(remaining) <= 3 else f" and {len(remaining) - 3} more"
            detail = f"qBittorrent did not remove torrent(s): {sample}{extra}" if remaining else "qBittorrent had missing selected torrent(s)."
            raise BatchRemoveError(succeeded, failed, detail)

    def _existing_torrent_hashes(self, hashes):
        existing = set()
        for t in self.c.torrents_info(torrent_hashes=hashes):
            h = str(getattr(t, "hash", "") or "").strip().lower()
            if h:
                existing.add(h)
        return existing

    def _wait_for_removed(self, hashes):
        remaining = set(h.lower() for h in hashes)
        for attempt in range(self._DELETE_VERIFY_ATTEMPTS):
            remaining = self._existing_torrent_hashes(hashes)
            if not remaining:
                return set()
            if attempt < self._DELETE_VERIFY_ATTEMPTS - 1:
                time.sleep(self._DELETE_VERIFY_DELAY_SECONDS)
        return remaining
    def add_torrent_url(self, u, sp=None):
        res = self.c.torrents_add(urls=u, save_path=sp)
        if isinstance(res, str) and res.strip().lower() == "fails.":
            raise RuntimeError("qBittorrent rejected the URL (Fails.)")
    def add_torrent_file(self, c, sp=None, p=None):
        res = self.c.torrents_add(torrent_files=c, save_path=sp)
        if isinstance(res, str) and res.strip().lower() == "fails.":
            raise RuntimeError("qBittorrent rejected the torrent file (Fails.)")
    def recheck_torrent(self, h): self.c.torrents_recheck(torrent_hashes=self._normalize_hash(h))
    def reannounce_torrent(self, h): self.c.torrents_reannounce(torrent_hashes=self._normalize_hash(h))
    def get_global_stats(self):
        i = self.c.transfer_info()
        return i.dl_info_speed, i.up_info_speed
    def get_app_preferences(self):
        return dict(self.c.app_preferences())
    def get_default_save_path(self):
        prefs = self.get_app_preferences()
        return prefs.get('save_path') if prefs else None
    def set_app_preferences(self, p):
        if not p:
            return
        self.c.app_set_preferences(prefs=p)
    def get_torrent_save_path(self, h):
        h = self._normalize_hash(h)
        inf = self.c.torrents_info(torrent_hashes=h)
        return inf[0].get('save_path') if inf else None
    def get_free_space(self, path):
        default_path = self.get_default_save_path()

        def _normalized(value):
            return str(value or "").strip().replace("\\", "/").rstrip("/").casefold()

        if path and default_path and _normalized(path) != _normalized(default_path):
            raise NotImplementedError(
                "qBittorrent reports free space only for its default save path."
            )
        data = self.c.sync_maindata()
        server_state = data.get("server_state", {}) if data else {}
        free_space = server_state.get("free_space_on_disk")
        if free_space is None:
            raise RuntimeError("qBittorrent did not report free disk space.")
        return int(free_space)
    def get_files(self, h):
        h = self._normalize_hash(h)
        fs = self.c.torrents_files(torrent_hash=h)
        return [{"index": i, "name": f.name, "size": f.size, "progress": f.progress, "priority": 1 if f.priority==1 else (2 if f.priority>=6 else 0)} for i, f in enumerate(fs)]
    def set_file_priority(self, h, i, p): self.c.torrents_file_priority(torrent_hash=self._normalize_hash(h), file_ids=i, priority=(1 if p==1 else (7 if p==2 else 0)))
    def get_peers(self, h):
        h = self._normalize_hash(h)
        pd = self.c.sync_torrent_peers(torrent_hash=h)
        return [{"address": k, "client": v.get('client','?'), "progress": v.get('progress',0), "down_rate": v.get('dl_speed',0), "up_rate": v.get('up_speed',0)} for k,v in pd.get('peers',{}).items()]
    def get_trackers(self, h):
        h = self._normalize_hash(h)
        ts = self.c.torrents_trackers(torrent_hash=h)
        return [{"url": t.get('url',''), "status": t.get('status_desc','?'), "peers": t.get('num_peers',0), "message": t.get('msg','')} for t in ts]

# --- Trans ---
from transmission_rpc import Client as TransClient
class TransmissionClient(BaseClient):
    supports_queue_reordering = True
    supports_move_storage = True
    supports_torrent_rate_limits = True
    supports_free_space_query = True

    def _add_new_magnet(self, url, save_path, start):
        self.c.add_torrent(url, download_dir=save_path, paused=not start)

    def find_magnet_duplicate(self, url):
        info_hash = parse_magnet_infohash(url)
        if not info_hash:
            return None
        torrents = self.c.get_torrents(ids=[info_hash], arguments=['hashString', 'name', 'trackers'])
        for torrent in torrents:
            existing_hash = self._field(torrent, 'hash_string', 'hashString', default='')
            if str(existing_hash).lower() == info_hash:
                trackers = self._collection(self._field(torrent, 'trackers', default=[]))
                return info_hash, self._field(torrent, 'name', default=info_hash), [
                    self._field(t, 'announce', default='') for t in trackers]
        return None

    def add_trackers(self, info_hash, trackers):
        torrent = self.c.get_torrent(info_hash, arguments=['trackers'])
        existing = {self._field(t, 'announce', default='') for t in
                    self._collection(self._field(torrent, 'trackers', default=[]))}
        new = [t for t in clean_tracker_urls(trackers) if t not in existing]
        if new:
            self.c.change_torrent(info_hash, tracker_add=new)

    DEFAULT_RPC_PATH = "/transmission/rpc"
    DEFAULT_PORT = 9091

    def __init__(self, u, us, pw):
        if not u.startswith(('http://', 'https://')):
            u = 'http://' + u
        p = urlparse(u)
        username = us if us not in (None, "") else p.username
        password = pw if pw not in (None, "") else p.password
        self.c = TransClient(
            host=p.hostname or "127.0.0.1",
            port=p.port or self.DEFAULT_PORT,
            username=username,
            password=password,
            protocol=p.scheme,
            path=p.path or self.DEFAULT_RPC_PATH,
        )

    def test_connection(self): return self.c.server_version

    def _field(self, obj, *names, default=None):
        for name in names:
            if isinstance(obj, dict) and name in obj:
                value = obj[name]
                if value is not None:
                    return value
                continue
            try:
                value = getattr(obj, name)
            except Exception:
                pass
            else:
                if value is not None:
                    return value
        return default

    def _collection(self, value):
        if value is None or isinstance(value, (str, bytes, bytearray)):
            return []
        if isinstance(value, dict):
            return list(value.values())
        return list(value)

    def _int(self, value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _bool(self, value, default=False):
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "on")
        return bool(value)

    def _eta_seconds(self, value):
        if value is None or value == "":
            return -1
        if hasattr(value, "total_seconds"):
            try:
                return int(value.total_seconds())
            except (TypeError, ValueError, OverflowError):
                return -1
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def _first_tracker_url(self, t):
        for tracker in self._collection(self._field(t, "trackers", default=[])):
            announce = self._field(tracker, "announce", "url", default="")
            if announce:
                return announce
        return ""

    def _swarm_counts(self, t):
        """Best-available swarm seed/leecher totals from tracker scrape stats."""
        seeds = leechers = 0
        try:
            for s in self._collection(self._field(t, "tracker_stats", "trackerStats", default=[])):
                sc = self._int(self._field(s, "seeder_count", "seederCount", default=-1), -1)
                lc = self._int(self._field(s, "leecher_count", "leecherCount", default=-1), -1)
                if sc >= 0 and sc > seeds:
                    seeds = sc
                if lc >= 0 and lc > leechers:
                    leechers = lc
        except Exception:
            pass
        return seeds, leechers

    def _completion_bytes(self, torrent):
        # Lifetime network traffic can include discarded/re-downloaded pieces
        # and excludes files that were already on disk when the torrent was added.
        size = max(0, self._int(self._field(torrent, "size_when_done", "sizeWhenDone",
                                          "total_size", "totalSize", default=0)))
        left = self._field(torrent, "left_until_done", "leftUntilDone")
        if left is not None:
            done = size - self._int(left)
        else:
            done = (self._int(self._field(torrent, "have_valid", "haveValid", default=0))
                    + self._int(self._field(torrent, "have_unchecked", "haveUnchecked", default=0)))
        return size, max(0, min(size, done))

    def get_torrents_full(self):
        try:
            ts = self.c.get_torrents()
            res = []
            for t in ts:
                sv, av, hv = 0, 0, 0
                status = self._field(t, "status", default="")
                if status == 'stopped':
                    sv = 0
                elif status in ['checking', 'check pending']:
                    hv, sv = 1, 1
                else:
                    sv, av = 1, 1
                tracker_url = self._first_tracker_url(t)
                tracker_domain = _safe_tracker_domain(tracker_url)
                seeds_total, leechers_total = self._swarm_counts(t)
                size, done = self._completion_bytes(t)
                ratio = self._float(self._field(t, "ratio", default=0.0)) * 1000
                res.append({"hash": self._field(t, "hash_string", "hashString", "hash", default=""), "name": self._field(t, "name", default=""), "size": size, "done": done, "up_total": self._int(self._field(t, "uploaded_ever", "uploadedEver", default=0)), "ratio": ratio, "state": sv, "active": av, "hashing": hv, "message": self._field(t, "error_string", "errorString", default=""), "down_rate": self._int(self._field(t, "rate_download", "rateDownload", default=0)), "up_rate": self._int(self._field(t, "rate_upload", "rateUpload", default=0)), "tracker_domain": tracker_domain, "eta": self._eta_seconds(self._field(t, "eta", default=-1)), "seeds_connected": self._int(self._field(t, "peers_sending_to_us", "peersSendingToUs", default=0)), "seeds_total": seeds_total, "leechers_connected": self._int(self._field(t, "peers_getting_from_us", "peersGettingFromUs", default=0)), "leechers_total": leechers_total, "availability": None, "queue_position": self._int(self._field(t, "queue_position", "queuePosition", default=-1), -1), "save_path": self._field(t, "download_dir", "downloadDir", default=None)})
            return res
        except Exception as e:
            print(f"Transmission error: {e}")
            raise

    def _normalize_torrent_id(self, h):
        if isinstance(h, int) and not isinstance(h, bool):
            return h
        return self._normalize_hash(h)

    def _normalize_torrent_ids(self, hs):
        if hs is None:
            return []
        if isinstance(hs, (str, bytes, bytearray, memoryview)) or isinstance(hs, int):
            hs = [hs]
        out = []
        for h in hs:
            if h is None:
                continue
            normalized = self._normalize_torrent_id(h)
            if normalized not in (None, ""):
                out.append(normalized)
        return out

    def start_torrent(self, h): self.c.start_torrent(self._normalize_torrent_id(h))
    def stop_torrent(self, h): self.c.stop_torrent(self._normalize_torrent_id(h))
    def queue_up(self, h): self.c.queue_up(self._normalize_torrent_id(h))
    def queue_down(self, h): self.c.queue_down(self._normalize_torrent_id(h))
    def queue_top(self, h): self.c.queue_top(self._normalize_torrent_id(h))
    def queue_bottom(self, h): self.c.queue_bottom(self._normalize_torrent_id(h))
    def move_torrent_data(self, h, destination):
        self.c.move_torrent_data(self._normalize_torrent_id(h), location=destination)
    def set_torrent_rate_limits(self, h, download_limit, upload_limit):
        download_limit = max(0, int(download_limit))
        upload_limit = max(0, int(upload_limit))
        self.c.change_torrent(
            self._normalize_torrent_id(h),
            download_limit=max(1, (download_limit + 999) // 1000) if download_limit else 0,
            download_limited=download_limit > 0,
            upload_limit=max(1, (upload_limit + 999) // 1000) if upload_limit else 0,
            upload_limited=upload_limit > 0,
        )
    def remove_torrent(self, h): self.c.remove_torrent(self._normalize_torrent_id(h), delete_data=False)
    def remove_torrent_with_data(self, h): self.c.remove_torrent(self._normalize_torrent_id(h), delete_data=True)
    def remove_torrents(self, hs, df=False):
        delete_data = self._normalize_delete_files(df)
        succeeded = 0
        failed = 0
        for h in self._normalize_torrent_ids(hs):
            try:
                self.c.remove_torrent(h, delete_data=delete_data)
                succeeded += 1
            except Exception:
                failed += 1
        if failed:
            raise BatchRemoveError(succeeded, failed)
    def add_torrent_url(self, u, sp=None): self.c.add_torrent(u, download_dir=sp)
    def add_torrent_file(self, c, sp=None, p=None):
        # Pass raw .torrent bytes; transmission_rpc base64-encodes them into metainfo.
        # (Passing a base64 *string* makes v4 treat it as a filename and silently fail.)
        options = {}
        if p is not None:
            options['files_wanted'] = [i for i, priority in enumerate(p) if priority > 0]
            options['files_unwanted'] = [i for i, priority in enumerate(p) if priority == 0]
        self.c.add_torrent(c, download_dir=sp, **options)
    def recheck_torrent(self, h): self.c.verify_torrent(self._normalize_torrent_id(h))
    def reannounce_torrent(self, h): self.c.reannounce_torrent(self._normalize_torrent_id(h))
    def get_global_stats(self):
        s = self.c.session_stats()
        return s.download_speed, s.upload_speed
    def _session_value(self, session, key):
        try:
            return getattr(session, key)
        except Exception:
            return None
    def get_app_preferences(self):
        session = self.c.get_session()
        keys = [
            "speed_limit_down_enabled", "speed_limit_down", "speed_limit_up_enabled", "speed_limit_up",
            "alt_speed_enabled", "alt_speed_down", "alt_speed_up", "alt_speed_time_enabled",
            "alt_speed_time_begin", "alt_speed_time_end", "alt_speed_time_day",
            "peer_port", "peer_port_random_on_start", "port_forwarding_enabled", "utp_enabled",
            "dht_enabled", "pex_enabled", "lpd_enabled", "encryption", "blocklist_enabled",
            "blocklist_url", "peer_limit_global", "peer_limit_per_torrent", "idle_seeding_limit_enabled",
            "idle_seeding_limit", "seedRatioLimited", "seedRatioLimit", "download_queue_enabled",
            "download_queue_size", "seed_queue_enabled", "seed_queue_size", "download_dir",
            "incomplete_dir_enabled", "incomplete_dir", "rename_partial_files",
            "trash_original_torrent_files", "start_added_torrents", "cache_size_mb",
            "script_torrent_done_enabled", "script_torrent_done_filename",
        ]
        prefs = {}
        for key in keys:
            if key == "seedRatioLimited":
                value = self._session_value(session, "seed_ratio_limited")
            elif key == "seedRatioLimit":
                value = self._session_value(session, "seed_ratio_limit")
            else:
                value = self._session_value(session, key)
            if value is not None:
                prefs[key] = value
        return prefs if prefs else None
    def get_default_save_path(self):
        prefs = self.get_app_preferences()
        return prefs.get('download_dir') if prefs else None
    def set_app_preferences(self, p):
        if not p:
            return
        mapping = {}
        valid_keys = {
            "speed_limit_down_enabled", "speed_limit_down", "speed_limit_up_enabled", "speed_limit_up",
            "alt_speed_enabled", "alt_speed_down", "alt_speed_up", "alt_speed_time_enabled",
            "alt_speed_time_begin", "alt_speed_time_end", "alt_speed_time_day",
            "peer_port", "peer_port_random_on_start", "port_forwarding_enabled", "utp_enabled",
            "dht_enabled", "pex_enabled", "lpd_enabled", "encryption", "blocklist_enabled",
            "blocklist_url", "peer_limit_global", "peer_limit_per_torrent", "idle_seeding_limit_enabled",
            "idle_seeding_limit", "seedRatioLimited", "seedRatioLimit", "download_queue_enabled",
            "download_queue_size", "seed_queue_enabled", "seed_queue_size", "download_dir",
            "incomplete_dir_enabled", "incomplete_dir", "rename_partial_files",
            "trash_original_torrent_files", "start_added_torrents", "cache_size_mb",
            "script_torrent_done_enabled", "script_torrent_done_filename",
        }
        for key, value in p.items():
            if key not in valid_keys:
                continue
            if key == "seedRatioLimited":
                mapping["seed_ratio_limited"] = value
            elif key == "seedRatioLimit":
                mapping["seed_ratio_limit"] = value
            else:
                mapping[key] = value
        if mapping:
            self.c.set_session(**mapping)
    def get_torrent_save_path(self, h):
        h = self._normalize_torrent_id(h)
        t = self.c.get_torrent(h)
        return self._field(t, 'download_dir', 'downloadDir', default=None)

    def get_free_space(self, path):
        return int(self.c.free_space(path))

    def get_files(self, h):
        h = self._normalize_torrent_id(h)
        t = self.c.get_torrent(h, arguments=['files', 'fileStats'])
        res = []
        files = self._collection(self._field(t, "files", default=[]))
        file_stats = self._collection(self._field(t, "file_stats", "fileStats", default=[]))
        for i, f in enumerate(files):
            s = file_stats[i] if i < len(file_stats) else {}
            size = self._int(self._field(f, "length", "size", default=0))
            completed = self._int(self._field(f, "bytes_completed", "bytesCompleted", default=0))
            wanted = self._bool(self._field(s, "wanted", default=True), True)
            priority_value = self._field(s, "priority", default=0)
            if isinstance(priority_value, str):
                priority = 2 if priority_value.strip().lower() == "high" else 1
            else:
                priority = 2 if self._int(priority_value) > 0 else 1
            res.append({"index": i, "name": self._field(f, "name", "filename", default=""), "size": size, "progress": completed/size if size>0 else 0, "priority": priority if wanted else 0})
        return res

    def set_file_priority(self, h, i, p):
        h = self._normalize_torrent_id(h)
        args = {}
        if p == 0:
            args['files_unwanted'] = [i]
        else:
            args['files_wanted'] = [i]
            args['priority_high' if p == 2 else 'priority_normal'] = [i]
        self.c.change_torrent(h, **args)

    def get_peers(self, h):
        h = self._normalize_torrent_id(h)
        t = self.c.get_torrent(h, arguments=['peers'])
        raw_peers = self._field(t, "peers", default=[])
        peer_items = raw_peers.items() if isinstance(raw_peers, dict) else [(None, p) for p in (raw_peers or [])]
        res = []
        for key, p in peer_items:
            address = self._field(p, "address", default="")
            port = self._field(p, "port", default=None)
            if address and port not in (None, ""):
                address = f"{address}:{port}"
            elif not address and key is not None:
                address = str(key)
            res.append({"address": address, "client": self._field(p, "client_name", "clientName", "client", default="?") or "?", "progress": self._float(self._field(p, "progress", default=0)), "down_rate": self._int(self._field(p, "rate_to_client", "rateToClient", "dl_speed", default=0)), "up_rate": self._int(self._field(p, "rate_from_client", "rateFromClient", "up_speed", default=0))})
        return res

    def get_trackers(self, h):
        h = self._normalize_torrent_id(h)
        t = self.c.get_torrent(h, arguments=['trackerStats'])
        stats = self._collection(self._field(t, "tracker_stats", "trackerStats", default=[]))
        return [{"url": self._field(s, "announce", "url", default=""), "status": "Active" if self._bool(self._field(s, "has_announced", "hasAnnounced", default=False)) else "?", "peers": self._int(self._field(s, "peer_count", "peerCount", default=0)), "message": self._field(s, "last_announce_result", "lastAnnounceResult", default="") or ''} for s in stats]

# --- Local ---
prepare_libtorrent_dlls()
try:
    import libtorrent as lt
except ImportError:
    lt = None
from session_manager import SessionManager
class LocalClient(BaseClient):
    supports_queue_reordering = True
    supports_move_storage = True
    supports_torrent_rate_limits = True
    supports_free_space_query = True
    def find_magnet_duplicate(self, url):
        info_hash = parse_magnet_infohash(url)
        if not info_hash:
            return None
        handle = self._gh(info_hash)
        if handle:
            return (info_hash, str(handle.status().name or info_hash),
                    [str(t['url']) for t in handle.trackers()])
        return None

    def _add_new_magnet(self, url, save_path, start):
        self.m.add_magnet(url, save_path or self._edp(), start=start)

    def add_trackers(self, info_hash, trackers):
        self.m.add_trackers(info_hash, trackers)

    def __init__(self, dp, us=None, pw=None):
        if not lt:
            raise RuntimeError("libtorrent not found.")
        self.m = SessionManager.get_instance()
        self.dp = dp if dp and os.path.isdir(dp) else os.getcwd()
    def _edp(self):
        from config_manager import ConfigManager
        p = ConfigManager().get_preferences().get('download_path')
        return p if p and os.path.isdir(p) else self.dp
    def test_connection(self):
        # libtorrent 2.1 dropped lt.version and only exposes lt.__version__.
        version = getattr(lt, "__version__", None) or getattr(lt, "version", None)
        return f"libtorrent {version or 'unknown'}"
    def _local_magnet_uri(self, handle, hashes):
        try:
            if _handle_has_metadata(handle) and hasattr(lt, "make_magnet_uri"):
                return lt.make_magnet_uri(_handle_torrent_info(handle))
        except Exception:
            pass
        return build_magnet_from_hashes(
            hashes.get("v1"),
            hashes.get("v2"),
            getattr(handle.status(), "name", None),
        )

    def get_torrents_full(self):
        try:
            hs = self.m.get_torrents()
        except Exception:
            raise
        res = []
        for h in hs:
            try:
                if not h.is_valid():
                    continue
                s = h.status()
                sv = 0 if (_torrent_status_flag(s, "paused") and not _torrent_status_flag(s, "auto_managed")) else 1
                if sv == 1 and s.state not in [lt.torrent_status.seeding, lt.torrent_status.finished]:
                    av = 1
                elif s.state == lt.torrent_status.seeding:
                    av = 1
                else:
                    av = 0
                hv = 1 if s.state in [
                    _torrent_state_value("checking_files"),
                    _torrent_state_value("queued_for_checking"),
                    _torrent_state_value("checking_resume_data"),
                ] else 0
                hashes = self.m._handle_hash_dict(h) if hasattr(self.m, "_handle_hash_dict") else {}
                ihs = hashes.get("v1") or hashes.get("v2") or self.m._handle_hash_key(h)
                if not ihs:
                    ih = h.info_hash()
                    ihs = str(ih)
                    if len(ihs) != 40:
                        ihs = binascii.hexlify(ih.to_string()).decode('ascii')
                ratio = (s.all_time_upload / s.all_time_download * 1000) if s.all_time_download > 0 else 0
                eta = int((s.total_wanted - s.total_wanted_done) / s.download_payload_rate) if s.download_payload_rate > 0 else -1
                ac = None
                try:
                    if hasattr(s, "distributed_copies"):
                        ac = float(s.distributed_copies)
                    elif hasattr(s, "distributed_full_copies"):
                        ac = float(s.distributed_full_copies) + (float(getattr(s, "distributed_fraction", 0)) / 1000.0)
                except Exception:
                    pass
                tracker_domain = _safe_tracker_domain(getattr(s, "current_tracker", "") or "")
                try:
                    queue_position = int(getattr(s, "queue_position", -1))
                except (TypeError, ValueError):
                    queue_position = -1
                row = {"hash": str(ihs), "name": str(s.name if s.name else ihs), "size": int(s.total_wanted), "done": int(s.total_wanted_done), "up_total": int(s.all_time_upload), "ratio": int(ratio), "state": int(sv), "active": int(av), "hashing": int(hv), "message": str(s.errc.message() if s.errc else ""), "down_rate": int(s.download_payload_rate), "up_rate": int(s.upload_payload_rate), "tracker_domain": tracker_domain, "save_path": str(getattr(s, 'save_path', None) or self._edp()), "eta": int(eta), "seeds_connected": int(getattr(s, 'num_seeds', 0)), "seeds_total": int(s.num_complete), "leechers_connected": int(max(0, int(getattr(s, 'num_peers', s.num_connections)) - int(getattr(s, 'num_seeds', 0)))), "leechers_total": int(s.num_incomplete), "availability": ac, "queue_position": queue_position}
                if hashes:
                    row["hashes"] = hashes
                    if hashes.get("v1"):
                        row["hash_v1"] = hashes["v1"]
                    if hashes.get("v2"):
                        row["hash_v2"] = hashes["v2"]
                    magnet = self._local_magnet_uri(h, hashes)
                    if magnet:
                        row["magnet"] = magnet
                res.append(row)
            except Exception as exc:
                # Never let one bad row blank the whole list (issue #1: an
                # AttributeError on every row made added torrents invisible).
                print(f"Skipping torrent row: {type(exc).__name__}: {exc}")
                continue
        return res
    def _require_handle(self, h):
        handle = self._gh(h)
        if not handle:
            raise LookupError("Torrent not found.")
        return handle
    def start_torrent(self, h):
        self._require_handle(h).resume()
    def stop_torrent(self, h):
        x = self._require_handle(h)
        # A manual stop must take the torrent out of auto-management:
        # the queue manager could otherwise restart it, and the GUI only
        # shows a torrent as Stopped when paused and NOT auto-managed.
        _handle_set_auto_managed(x, False)
        x.pause()
    def queue_up(self, h):
        self._require_handle(h).queue_position_up()
    def queue_down(self, h):
        self._require_handle(h).queue_position_down()
    def queue_top(self, h):
        self._require_handle(h).queue_position_top()
    def queue_bottom(self, h):
        self._require_handle(h).queue_position_bottom()
    def move_torrent_data(self, h, destination):
        self._require_handle(h).move_storage(destination)
    def set_torrent_rate_limits(self, h, download_limit, upload_limit):
        handle = self._require_handle(h)
        download_limit = int(download_limit)
        upload_limit = int(upload_limit)
        handle.set_download_limit(download_limit if download_limit > 0 else -1)
        handle.set_upload_limit(upload_limit if upload_limit > 0 else -1)
    def remove_torrent(self, h): self.m.remove_torrent(h, False)
    def remove_torrent_with_data(self, h): self.m.remove_torrent(h, True)
    def add_torrent_url(self, u, sp=None):
        fp = sp or self._edp()
        if u.lower().startswith("magnet:"):
            self.m.add_magnet(u, fp)
        else:
            self.m.add_torrent_file(download_torrent_url(u), fp)
    def add_torrent_file(self, c, sp=None, pr=None): self.m.add_torrent_file(c, sp or self._edp(), pr)
    def get_global_stats(self):
        st = self.m.get_status()
        return st.payload_download_rate, st.payload_upload_rate
    def _gh(self, i):
        return self.m._find_handle(i)
    def recheck_torrent(self, h):
        x = self._require_handle(h)
        if not _handle_has_metadata(x):
            # libtorrent ignores force_recheck without metadata; say so.
            raise RuntimeError("Torrent metadata has not been received from peers yet, so its files cannot be checked.")
        x.force_recheck()
    def reannounce_torrent(self, h):
        self._require_handle(h).force_reannounce()
    def get_torrent_save_path(self, h):
        x = self._gh(h)
        return getattr(x.status(), 'save_path', None) if x else None
    def get_free_space(self, path):
        return int(shutil.disk_usage(path).free)
    def get_files(self, h):
        x = self._gh(h)
        if not x or not _handle_has_metadata(x):
            return []
        ti = _handle_torrent_info(x)
        if ti is None:
            return []
        fs = torrent_file_storage(ti)
        pr = x.file_progress()
        prio = _handle_file_priorities(x)
        return [{"index": i, "name": fs.file_path(i), "size": fs.file_size(i), "progress": pr[i]/fs.file_size(i) if fs.file_size(i)>0 else 0, "priority": 1 if prio[i]==4 else (2 if prio[i]>4 else 0)} for i in range(ti.num_files())]
    def set_file_priority(self, h, i, p):
        x = self._require_handle(h)
        previous = list(_handle_file_priorities(x))
        x.file_priority(i, 4 if p==1 else (7 if p==2 else 0))
        try:
            self.m.update_priorities(self.m._handle_hash_key(x) or h, _handle_file_priorities(x))
        except Exception:
            if 0 <= i < len(previous):
                x.file_priority(i, previous[i])
            raise
    def get_peers(self, h):
        x = self._gh(h)
        if not x:
            return []
        return [{"address": str(p.ip), "client": str(p.client), "progress": float(p.progress), "down_rate": int(p.down_speed), "up_rate": int(p.up_speed)} for p in x.get_peer_info()]
    def get_trackers(self, h):
        x = self._gh(h)
        if not x:
            return []
        return [{"url": str(t['url']), "status": "Working" if t['verified'] else "?", "peers": 0, "message": str(t.get('message',''))} for t in x.trackers()]
    def get_app_preferences(self):
        from config_manager import ConfigManager
        return ConfigManager().get_preferences()
    def get_default_save_path(self):
        return self._edp()
    def set_app_preferences(self, p):
        from config_manager import ConfigManager
        cm = ConfigManager()
        prefs = cm.get_preferences()
        prefs.update(p)
        cm.set_preferences(prefs)
        self.m.apply_preferences(prefs)
