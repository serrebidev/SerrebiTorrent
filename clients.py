# ruff: noqa: E402

import abc
import binascii
import ipaddress
import os
import re
import socket
import time
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests
from torrent_parsing import build_magnet_from_hashes

MAX_TORRENT_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_TORRENT_URL_REDIRECTS = 5
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


def download_torrent_url(url, timeout=30):
    current = url
    for _ in range(MAX_TORRENT_URL_REDIRECTS + 1):
        validate_public_torrent_url(current)
        content = b""
        with requests.get(safe_encode_url(current), timeout=timeout, stream=True, allow_redirects=False) as r:
            if r.status_code in _REDIRECT_STATUSES:
                location = r.headers.get("Location")
                if not location:
                    raise ValueError("Torrent URL redirect missing Location header.")
                current = urljoin(current, location)
                continue
            r.raise_for_status()
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue
                content += chunk
                if len(content) > MAX_TORRENT_DOWNLOAD_BYTES:
                    raise ValueError("Torrent download exceeds 64 MB limit.")
        return content
    raise ValueError("Torrent URL redirected too many times.")


from libtorrent_env import prepare_libtorrent_dlls

def _safe_tracker_domain(tracker_url):
    if not tracker_url:
        return ""
    try:
        return urlparse(tracker_url).hostname or ""
    except Exception:
        return ""

class BaseClient(abc.ABC):
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
        for h in hashes:
            if not h:
                continue
            if delete_files:
                self.remove_torrent_with_data(h)
            else:
                self.remove_torrent(h)

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
                rd = b""
                while True:
                    ch = s.recv(4096)
                    if not ch:
                        break
                    rd += ch
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
            return []

    def start_torrent(self, h):
        self.srv.d.open(h)
        self.srv.d.start(h)

    def stop_torrent(self, h):
        self.srv.d.stop(h)
        self.srv.d.close(h)

    def remove_torrent(self, h):
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
        try:
            return self.srv.throttle.global_down.rate(), self.srv.throttle.global_up.rate()
        except Exception:
            return 0, 0

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
        self.srv.d.check_hash(h)

    def reannounce_torrent(self, h):
        self.srv.d.tracker_announce(h)

    def get_torrent_save_path(self, h):
        return self.srv.d.directory(h)

    def get_files(self, h):
        try:
            r = self.srv.f.multicall(h, "", "f.get_path=", "f.get_size_bytes=", "f.get_priority=", "f.get_completed_chunks=", "f.get_size_chunks=")
            return [{"index": i, "name": x[0], "size": x[1], "progress": x[3]/x[4] if x[4]>0 else 0, "priority": x[2]} for i, x in enumerate(r)]
        except Exception:
            return []

    def set_file_priority(self, h, i, p):
        self.srv.f.priority.set(h, i, p)
        self.srv.d.update_priorities(h)

    def get_peers(self, h):
        try:
            r = self.srv.p.multicall(h, "", "p.address=", "p.client_version=", "p.completed_percent=", "p.down_rate=", "p.up_rate=")
            return [{"address": str(x[0]), "client": str(x[1]), "progress": float(x[2])/100.0, "down_rate": int(x[3]), "up_rate": int(x[4])} for x in r]
        except Exception:
            return []

    def get_trackers(self, h):
        try:
            r = self.srv.t.multicall(h, "", "t.url=", "t.is_enabled=", "t.scrape_complete=")
            return [{"url": str(x[0]), "status": "Enabled" if x[1] else "Disabled", "peers": int(x[2]) if x[2] else 0, "message": ""} for x in r]
        except Exception:
            return []

# --- qBit ---
import qbittorrentapi
class QBittorrentClient(BaseClient):
    _DELETE_VERIFY_ATTEMPTS = 5
    _DELETE_VERIFY_DELAY_SECONDS = 0.2

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
                res.append({"hash": t.hash, "name": t.name, "size": t.total_size, "done": t.completed, "up_total": t.uploaded, "ratio": t.ratio * 1000, "state": sv, "active": av, "hashing": hv, "message": message, "down_rate": t.dlspeed, "up_rate": t.upspeed, "tracker_domain": tracker_domain, "eta": int(getattr(t, "eta", -1) or -1), "seeds_connected": int(getattr(t, "num_seeds", 0) or 0), "seeds_total": int(getattr(t, "num_complete", 0) or 0), "leechers_connected": int(getattr(t, "num_leechs", 0) or 0), "leechers_total": int(getattr(t, "num_incomplete", 0) or 0), "availability": getattr(t, "availability", None), "save_path": getattr(t, "save_path", None)})
            return res
        except Exception as e:
            print(f"qBittorrent error: {e}")
            return []
    def start_torrent(self, h): self._torrent_action("torrents_start", "torrents_resume", h)
    def stop_torrent(self, h): self._torrent_action("torrents_stop", "torrents_pause", h)
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
            raise RuntimeError("qBittorrent has no matching torrent for the selected hash.")

        to_delete = [h for h in hashes if h.lower() in existing]
        self.c.torrents_delete(torrent_hashes=to_delete, delete_files=self._normalize_delete_files(df))
        remaining = self._wait_for_removed(to_delete)
        if remaining:
            sample = ", ".join(sorted(remaining)[:3])
            extra = "" if len(remaining) <= 3 else f" and {len(remaining) - 3} more"
            raise RuntimeError(f"qBittorrent did not remove torrent(s): {sample}{extra}")

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
    def recheck_torrent(self, h): self.c.torrents_recheck(torrent_hashes=h)
    def reannounce_torrent(self, h): self.c.torrents_reannounce(torrent_hashes=h)
    def get_global_stats(self):
        i = self.c.transfer_info()
        return i.dl_info_speed, i.up_info_speed
    def get_app_preferences(self):
        try:
            return dict(self.c.app_preferences())
        except Exception as e:
            print(f"qBittorrent prefs error: {e}")
            return None
    def get_default_save_path(self):
        prefs = self.get_app_preferences()
        return prefs.get('save_path') if prefs else None
    def set_app_preferences(self, p):
        if not p:
            return
        self.c.app_set_preferences(prefs=p)
    def get_torrent_save_path(self, h):
        inf = self.c.torrents_info(torrent_hashes=h)
        return inf[0].get('save_path') if inf else None
    def get_files(self, h):
        fs = self.c.torrents_files(torrent_hash=h)
        return [{"index": i, "name": f.name, "size": f.size, "progress": f.progress, "priority": 1 if f.priority==1 else (2 if f.priority>=6 else 0)} for i, f in enumerate(fs)]
    def set_file_priority(self, h, i, p): self.c.torrents_file_priority(torrent_hash=h, file_ids=i, priority=(1 if p==1 else (7 if p==2 else 0)))
    def get_peers(self, h):
        pd = self.c.sync_torrent_peers(torrent_hash=h)
        return [{"address": k, "client": v.get('client','?'), "progress": v.get('progress',0), "down_rate": v.get('dl_speed',0), "up_rate": v.get('up_speed',0)} for k,v in pd.get('peers',{}).items()]
    def get_trackers(self, h):
        ts = self.c.torrents_trackers(torrent_hash=h)
        return [{"url": t.get('url',''), "status": t.get('status_desc','?'), "peers": t.get('num_peers',0), "message": t.get('msg','')} for t in ts]

# --- Trans ---
from transmission_rpc import Client as TransClient
class TransmissionClient(BaseClient):
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
                ratio = self._float(self._field(t, "ratio", default=0.0)) * 1000
                res.append({"hash": self._field(t, "hash_string", "hashString", "hash", default=""), "name": self._field(t, "name", default=""), "size": self._int(self._field(t, "total_size", "totalSize", default=0)), "done": self._int(self._field(t, "downloaded_ever", "downloadedEver", default=0)), "up_total": self._int(self._field(t, "uploaded_ever", "uploadedEver", default=0)), "ratio": ratio, "state": sv, "active": av, "hashing": hv, "message": self._field(t, "error_string", "errorString", default=""), "down_rate": self._int(self._field(t, "rate_download", "rateDownload", default=0)), "up_rate": self._int(self._field(t, "rate_upload", "rateUpload", default=0)), "tracker_domain": tracker_domain, "eta": self._eta_seconds(self._field(t, "eta", default=-1)), "seeds_connected": self._int(self._field(t, "peers_sending_to_us", "peersSendingToUs", default=0)), "seeds_total": seeds_total, "leechers_connected": self._int(self._field(t, "peers_getting_from_us", "peersGettingFromUs", default=0)), "leechers_total": leechers_total, "availability": None, "save_path": self._field(t, "download_dir", "downloadDir", default=None)})
            return res
        except Exception as e:
            print(f"Transmission error: {e}")
            return []

    def start_torrent(self, h): self.c.start_torrent(h)
    def stop_torrent(self, h): self.c.stop_torrent(h)
    def remove_torrent(self, h): self.c.remove_torrent(h, delete_data=False)
    def remove_torrent_with_data(self, h): self.c.remove_torrent(h, delete_data=True)
    def add_torrent_url(self, u, sp=None): self.c.add_torrent(u, download_dir=sp)
    def add_torrent_file(self, c, sp=None, p=None):
        # Pass raw .torrent bytes; transmission_rpc base64-encodes them into metainfo.
        # (Passing a base64 *string* makes v4 treat it as a filename and silently fail.)
        self.c.add_torrent(c, download_dir=sp)
    def recheck_torrent(self, h): self.c.verify_torrent(h)
    def reannounce_torrent(self, h): self.c.reannounce_torrent(h)
    def get_global_stats(self):
        s = self.c.session_stats()
        return s.download_speed, s.upload_speed
    def _session_value(self, session, key):
        try:
            return getattr(session, key)
        except Exception:
            return None
    def get_app_preferences(self):
        try:
            session = self.c.get_session()
        except Exception as e:
            print(f"Transmission prefs error: {e}")
            return None
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
        t = self.c.get_torrent(h)
        return self._field(t, 'download_dir', 'downloadDir', default=None)

    def get_files(self, h):
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
        args = {}
        if p == 0:
            args['files_unwanted'] = [i]
        else:
            args['files_wanted'] = [i]
            args['priority_high' if p == 2 else 'priority_normal'] = [i]
        self.c.change_torrent(h, **args)

    def get_peers(self, h):
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
    def __init__(self, dp, us=None, pw=None):
        if not lt:
            raise RuntimeError("libtorrent not found.")
        self.m = SessionManager.get_instance()
        self.dp = dp if dp and os.path.isdir(dp) else os.getcwd()
    def _edp(self):
        from config_manager import ConfigManager
        p = ConfigManager().get_preferences().get('download_path')
        return p if p and os.path.isdir(p) else self.dp
    def test_connection(self): return f"libtorrent {lt.version}"
    def _local_magnet_uri(self, handle, hashes):
        try:
            if handle.has_metadata() and hasattr(lt, "make_magnet_uri"):
                return lt.make_magnet_uri(handle.get_torrent_info())
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
            return []
        res = []
        for h in hs:
            try:
                if not h.is_valid():
                    continue
                s = h.status()
                sv = 0 if (s.paused and not s.auto_managed) else 1
                if sv == 1 and s.state not in [lt.torrent_status.seeding, lt.torrent_status.finished]:
                    av = 1
                elif s.state == lt.torrent_status.seeding:
                    av = 1
                else:
                    av = 0
                hv = 1 if s.state in [lt.torrent_status.checking_files, lt.torrent_status.queued_for_checking] else 0
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
                row = {"hash": str(ihs), "name": str(s.name if s.name else ihs), "size": int(s.total_wanted), "done": int(s.total_wanted_done), "up_total": int(s.all_time_upload), "ratio": int(ratio), "state": int(sv), "active": int(av), "hashing": int(hv), "message": str(s.errc.message() if s.errc else ""), "down_rate": int(s.download_payload_rate), "up_rate": int(s.upload_payload_rate), "tracker_domain": tracker_domain, "save_path": str(getattr(s, 'save_path', None) or self._edp()), "eta": int(eta), "seeds_connected": int(getattr(s, 'num_seeds', 0)), "seeds_total": int(s.num_complete), "leechers_connected": int(max(0, int(getattr(s, 'num_peers', s.num_connections)) - int(getattr(s, 'num_seeds', 0)))), "leechers_total": int(s.num_incomplete), "availability": ac}
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
            except Exception:
                continue
        return res
    def start_torrent(self, h):
        x = self._gh(h)
        if x:
            x.resume()
    def stop_torrent(self, h):
        x = self._gh(h)
        if x:
            x.pause()
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
        x = self._gh(h)
        if x:
            x.force_recheck()
    def reannounce_torrent(self, h):
        x = self._gh(h)
        if x:
            x.force_reannounce()
    def get_torrent_save_path(self, h):
        x = self._gh(h)
        return getattr(x.status(), 'save_path', None) if x else None
    def get_files(self, h):
        x = self._gh(h)
        if not x or not x.has_metadata():
            return []
        ti = x.get_torrent_info()
        fs = ti.files()
        pr = x.file_progress()
        prio = x.file_priorities()
        return [{"index": i, "name": fs.file_path(i), "size": fs.file_size(i), "progress": pr[i]/fs.file_size(i) if fs.file_size(i)>0 else 0, "priority": 1 if prio[i]==4 else (2 if prio[i]>4 else 0)} for i in range(ti.num_files())]
    def set_file_priority(self, h, i, p):
        x = self._gh(h)
        if x:
            x.file_priority(i, 4 if p==1 else (7 if p==2 else 0))
            self.m.update_priorities(self.m._handle_hash_key(x) or h, x.file_priorities())
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
