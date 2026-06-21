#!/usr/bin/env python3
# ruff: noqa: E402

import sys
import os

# Add current dir to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from libtorrent_env import prepare_libtorrent_dlls
prepare_libtorrent_dlls()

import qbittorrentapi
from clients import RTorrentClient, TransmissionClient
from config_manager import ConfigManager

def format_size(bytes_size):
    """Format bytes to human readable."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"

def format_time(seconds):
    """Format seconds to time string."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = -1
    if seconds == -1 or seconds == 8640000:  # qBit infinite
        return "∞"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

def get_status(t):
    """Get status string from torrent."""
    state = str(t.state or "")
    state_key = state.lower()
    if state_key in ['downloading', 'metadl', 'forcedmetadl', 'forceddl']:
        return "Downloading"
    elif state_key in ['uploading', 'forcedup']:
        return "Seeding"
    elif state_key in ['pauseddl', 'pausedup', 'stoppeddl', 'stoppedup']:
        return "Paused"
    elif 'checking' in state_key:
        return "Checking"
    elif state_key in ['stalleddl', 'stalledup']:
        return "Stalled"
    elif state_key == 'queueddl':
        return "Queued DL"
    elif state_key == 'queuedup':
        return "Queued UP"
    elif state_key == 'allocating':
        return "Allocating"
    elif state_key == 'moving':
        return "Moving"
    elif state_key in ['error', 'missingfiles']:
        return "Failed"
    else:
        return state.capitalize()

def _message_indicates_error(message):
    """Mirror main.clean_status_message: ignore benign 'no error' strings.

    Some backends surface localized Windows success strings (e.g. "The operation
    completed successfully.") in the error field for perfectly healthy torrents;
    treating those as failures would mislabel seeding/downloading rows.
    """
    low = str(message or "").strip().lower()
    if not low or low in ("success", "ok", "no error", "none"):
        return False
    if low.rstrip(".").strip() == "the operation completed successfully":
        return False
    if "the operation completed successfully" in low:
        return False
    if "the handle is invalid" in low:
        return False
    return True


def get_row_status(t):
    """Get status string from normalized client row dictionaries."""
    state = int(t.get('state', 0) or 0)
    hashing = int(t.get('hashing', 0) or 0)
    message = str(t.get('message', '') or '').strip()
    size = int(t.get('size', 0) or 0)
    done = int(t.get('done', 0) or 0)
    pct = (done / size * 100) if size > 0 else 0
    if _message_indicates_error(message):
        return "Failed"
    if hashing:
        return "Checking"
    if state == 1 and pct >= 100:
        return "Seeding"
    if state == 1:
        return "Downloading"
    if state == 0:
        return "Paused"
    return "Unknown"

def format_peer_pair(connected, total):
    try:
        connected = int(connected or 0)
    except (TypeError, ValueError):
        connected = 0
    try:
        total = int(total or 0)
    except (TypeError, ValueError):
        total = 0
    return f"{connected}/{total}"

def main():
    config = ConfigManager()
    profiles = config.get_profiles()
    default_profile = config.get_default_profile_id()

    if not default_profile or default_profile not in profiles:
        print("No default profile set or invalid.")
        return

    profile = profiles[default_profile]
    client_type = profile.get('type')
    url = profile.get('url')
    user = profile.get('user')
    password = profile.get('password')

    if client_type not in ['qbittorrent', 'rtorrent', 'transmission']:
        print("Only qBittorrent, Transmission, and rTorrent supported.")
        return

    try:
        if client_type == 'qbittorrent':
            print(f"Connecting to qBittorrent at {url} as {user}")
            client = qbittorrentapi.Client(host=url, username=user, password=password)
            client.auth_log_in()
            print("Logged in successfully")
            torrents = client.torrents_info()
        elif client_type == 'rtorrent':
            print(f"Connecting to rTorrent at {url}")
            client = RTorrentClient(url, user, password)
            client.test_connection()
            print("Connected successfully")
            torrents = client.get_torrents_full()
        elif client_type == 'transmission':
            print(f"Connecting to Transmission at {url}")
            client = TransmissionClient(url, user, password)
            client.test_connection()
            print("Connected successfully")
            torrents = client.get_torrents_full()

        print(f"Found {len(torrents)} torrents")

        print("Name | Size | Status | Downloaded % | Time Left | Seeds | Leechers")
        print("-" * 80)

        for t in torrents:
            if client_type == 'qbittorrent':
                name = t.name[:50]
                size = format_size(t.total_size)
                status = get_status(t)
                done_percent = (t.completed / t.total_size * 100) if t.total_size > 0 else 0
                done_str = f"{done_percent:.1f}%"
                time_left = format_time(t.eta)
                seeds = f"{t.num_seeds}/{t.num_complete}"
                leechers = f"{t.num_leechs}/{t.num_incomplete}"
            elif client_type in ('rtorrent', 'transmission'):
                name = t['name'][:50]
                size = format_size(t['size'])
                status = get_row_status(t)
                done_percent = (t['done'] / t['size'] * 100) if t['size'] > 0 else 0
                done_str = f"{done_percent:.1f}%"
                time_left = format_time(t.get('eta', -1))
                seeds = format_peer_pair(t.get('seeds_connected'), t.get('seeds_total'))
                leechers = format_peer_pair(t.get('leechers_connected'), t.get('leechers_total'))

            print(f"{name} | {size} | {status} | {done_str} | {time_left} | {seeds} | {leechers}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
