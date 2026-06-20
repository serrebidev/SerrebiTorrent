#!/usr/bin/env python3
# ruff: noqa: E402

import sys
import os

# Add current dir to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from libtorrent_env import prepare_libtorrent_dlls
prepare_libtorrent_dlls()

import qbittorrentapi
from clients import RTorrentClient
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
    state = t.state
    if state in ['downloading', 'metaDL', 'forcedDL']:
        return "Downloading"
    elif state in ['uploading', 'forcedUP']:
        return "Seeding"
    elif state in ['pausedDL', 'pausedUP']:
        return "Paused"
    elif 'checking' in state:
        return "Checking"
    elif state in ['stalledDL', 'stalledUP']:
        return "Stalled"
    elif state == 'queuedDL':
        return "Queued DL"
    elif state == 'queuedUP':
        return "Queued UP"
    elif state == 'allocating':
        return "Allocating"
    elif state == 'moving':
        return "Moving"
    else:
        return state.capitalize()

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

    if client_type not in ['qbittorrent', 'rtorrent']:
        print("Only qBittorrent and rTorrent supported.")
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
            elif client_type == 'rtorrent':
                name = t['name'][:50]
                size = format_size(t['size'])
                # Status from state and active
                state = t['state']
                active = t['active']
                hashing = t['hashing']
                if hashing:
                    status = "Checking"
                elif state == 1 and active == 1:
                    status = "Downloading"
                elif state == 1 and active == 0:
                    status = "Seeding"
                elif state == 0:
                    status = "Paused"
                else:
                    status = "Unknown"
                done_percent = (t['done'] / t['size'] * 100) if t['size'] > 0 else 0
                done_str = f"{done_percent:.1f}%"
                # Time left
                down_rate = t['down_rate']
                remaining = t['size'] - t['done']
                if down_rate > 0 and remaining > 0:
                    time_left = format_time(remaining // down_rate)
                else:
                    time_left = "∞"
                # Seeds/leechers not available in basic rTorrent, set to N/A
                seeds = "N/A"
                leechers = "N/A"

            print(f"{name} | {size} | {status} | {done_str} | {time_left} | {seeds} | {leechers}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
