"""Config management for SerrebiTorrent.

Goals:
- Store config in the app data directory (portable SerrebiTorrent_Data when writable).
- Migrate legacy config.json that lived next to main.py / the EXE.
- Keep a stable, minimal API used by the GUI.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from typing import Any, Dict

from app_paths import get_config_path, get_portable_base_dir


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: Dict[str, Any]) -> None:
    """Atomically write JSON: serialize to a temp file, fsync, then os.replace.

    A direct ``open(path, "w")`` truncates the real file immediately, so a crash
    or power loss mid-write leaves config.json empty and the user loses every
    profile/preference. Writing to a sibling temp and atomically renaming keeps
    the previous good file intact on any failure.
    """
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


CONFIG_FILE = get_config_path()
LEGACY_CONFIG_FILE = os.path.join(get_portable_base_dir(), "config.json")


DEFAULT_PREFERENCES: Dict[str, Any] = {
    "download_path": os.path.join(os.path.expanduser("~"), "Downloads"),
    "dl_limit": 0,  # 0 = unlimited (bytes/s)
    "ul_limit": 0,  # 0 = unlimited (bytes/s)
    "max_connections": -1,  # -1 = unlimited
    "max_uploads": -1,  # -1 = unlimited
    "listen_port": 6881,
    "announce_ip": "",  # IP reported to trackers (e.g. a public relay/VPS address); blank = auto
    "enable_upnp": True,
    "enable_natpmp": True,
    "enable_dht": True,
    "enable_lsd": True,
    "auto_start": True,
    "min_to_tray": True,
    "close_to_tray": True,
    "auto_check_updates": True,
    "enable_trackers": True,
    "tracker_url": "https://raw.githubusercontent.com/scriptzteam/BitTorrent-Tracker-List/refs/heads/main/trackers_best.txt",
    "rss_update_interval": 300,  # Default 5 minutes
    "web_ui_enabled": False,
    "web_ui_host": "127.0.0.1",
    "web_ui_port": 8080,
    "web_ui_user": "admin",
    "web_ui_pass": "password",
    # 0=None, 1=SOCKS4, 2=SOCKS5, 3=HTTP
    "proxy_type": 0,
    "proxy_host": "",
    "proxy_port": 8080,
    "proxy_user": "",
    "proxy_password": "",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "default_profile": "",
    "profiles": {},  # uuid -> profile_dict
    "preferences": DEFAULT_PREFERENCES,
}


def _ensure_valid_default_profile(cfg: Dict[str, Any]) -> None:
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        cfg["profiles"] = profiles

    default_profile = str(cfg.get("default_profile") or "")
    if profiles:
        if default_profile not in profiles:
            default_profile = next(iter(profiles))
    else:
        default_profile = ""
    cfg["default_profile"] = default_profile


class ConfigManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.config: Dict[str, Any] = self.load_config()

    def _normalize(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        # Ensure preferences exist and contain all required keys.
        prefs = cfg.get("preferences")
        if not isinstance(prefs, dict):
            prefs = {}
        for k, v in DEFAULT_PREFERENCES.items():
            prefs.setdefault(k, v)
        cfg["preferences"] = prefs

        profiles = cfg.get("profiles")
        if not isinstance(profiles, dict):
            cfg["profiles"] = {}

        _ensure_valid_default_profile(cfg)
        return cfg

    def load_config(self) -> Dict[str, Any]:
        cfg = None
        
        # Prefer the new path.
        if os.path.exists(CONFIG_FILE):
            try:
                cfg = self._normalize(_read_json(CONFIG_FILE))
            except Exception:
                cfg = None # Fallback

        # Migrate legacy config.json if present and no new config
        if not cfg and os.path.exists(LEGACY_CONFIG_FILE):
            try:
                cfg = self._normalize(_read_json(LEGACY_CONFIG_FILE))
                # Save to the new location. Keep the legacy file untouched.
                try:
                    _write_json(CONFIG_FILE, cfg)
                except Exception:
                    pass
            except Exception:
                cfg = None

        # First run or fallback: create a default config.
        if not cfg:
            cfg = DEFAULT_CONFIG.copy()
            # Ensure fresh copy of prefs
            cfg["preferences"] = DEFAULT_PREFERENCES.copy()
        
        # Ensure a default Local profile exists if list is empty
        profiles = cfg.get("profiles", {})
        if not profiles:
            import uuid
            pid = str(uuid.uuid4())
            dl_path = cfg["preferences"].get("download_path", "")
            if not dl_path:
                dl_path = os.path.join(os.path.expanduser("~"), "Downloads")
                
            cfg["profiles"] = {
                pid: {
                    "name": "Local",
                    "type": "local",
                    "url": dl_path,
                    "user": "",
                    "password": ""
                }
            }
            cfg["default_profile"] = pid
            
            # Save immediately if it was a fresh creation
            try:
                _write_json(CONFIG_FILE, cfg)
            except Exception:
                pass

        return cfg

    def save_config(self) -> None:
        with self.lock:
            _write_json(CONFIG_FILE, self.config)

    def get_preferences(self) -> Dict[str, Any]:
        with self.lock:
             return dict(self.config.get("preferences", DEFAULT_PREFERENCES.copy()))

    def set_preferences(self, prefs: Dict[str, Any]) -> None:
        with self.lock:
            self.config["preferences"] = dict(prefs)
            self.save_config()

    def get_profiles(self) -> Dict[str, Any]:
        with self.lock:
            profiles = self.config.get("profiles", {})
            return copy.deepcopy(profiles) if isinstance(profiles, dict) else {}

    def add_profile(self, name: str, client_type: str, url: str, user: str, password: str) -> str:
        import uuid

        pid = str(uuid.uuid4())
        with self.lock:
            self.config.setdefault("profiles", {})[pid] = {
                "name": name,
                "type": client_type,
                "url": url,
                "user": user,
                "password": password,
            }
            _ensure_valid_default_profile(self.config)
            self.save_config()
        return pid

    def update_profile(self, pid: str, name: str, client_type: str, url: str, user: str, password: str) -> None:
        with self.lock:
            if pid in self.get_profiles():
                self.config["profiles"][pid].update(
                    {
                        "name": name,
                        "type": client_type,
                        "url": url,
                        "user": user,
                        "password": password,
                    }
                )
                self.save_config()

    def delete_profile(self, pid: str) -> None:
        with self.lock:
            if pid in self.get_profiles():
                del self.config["profiles"][pid]
                _ensure_valid_default_profile(self.config)
                self.save_config()

    def get_default_profile_id(self) -> str:
        with self.lock:
            return str(self.config.get("default_profile", ""))

    def set_default_profile_id(self, pid: str) -> None:
        with self.lock:
            self.config["default_profile"] = pid
            _ensure_valid_default_profile(self.config)
            self.save_config()

    def get_profile(self, pid: str):
        with self.lock:
            return self.get_profiles().get(pid)
