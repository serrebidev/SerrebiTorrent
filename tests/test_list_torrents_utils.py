
import pytest
import sys
import os

# Add parent directory to path to import list_torrents
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from list_torrents import format_peer_pair, format_size, format_time, get_row_status, get_status, main

class MockTorrent:
    def __init__(self, state):
        self.state = state

def test_format_size():
    assert format_size(100) == "100.00 B"
    assert format_size(1024) == "1.00 KB"
    assert format_size(1024 * 1024) == "1.00 MB"
    assert format_size(1024 * 1024 * 1024) == "1.00 GB"
    assert format_size(1024 * 1024 * 1024 * 1024) == "1.00 TB"

def test_format_time():
    assert format_time(-1) == "∞"
    assert format_time(8640000) == "∞"
    assert format_time(30) == "30s"
    assert format_time(90) == "1m 30s"
    assert format_time(3600) == "1h 0m 0s"
    assert format_time(3665) == "1h 1m 5s"
    assert format_time(86400) == "1d 0h 0m"
    assert format_time(90065) == "1d 1h 1m"

def test_get_status():
    assert get_status(MockTorrent('downloading')) == "Downloading"
    assert get_status(MockTorrent('uploading')) == "Seeding"
    assert get_status(MockTorrent('metaDL')) == "Downloading"
    assert get_status(MockTorrent('forcedMetaDL')) == "Downloading"
    assert get_status(MockTorrent('pausedDL')) == "Paused"
    assert get_status(MockTorrent('stoppedDL')) == "Paused"
    assert get_status(MockTorrent('checkingUP')) == "Checking"
    assert get_status(MockTorrent('stalledDL')) == "Stalled"
    assert get_status(MockTorrent('queuedDL')) == "Queued DL"
    assert get_status(MockTorrent('queuedUP')) == "Queued UP"
    assert get_status(MockTorrent('missingFiles')) == "Failed"
    assert get_status(MockTorrent('error')) == "Failed"
    assert get_status(MockTorrent('unknown')) == "Unknown"

def test_normalized_row_formatting_helpers():
    assert get_row_status({"state": 1, "hashing": 0, "size": 100, "done": 50, "message": ""}) == "Downloading"
    assert get_row_status({"state": 1, "hashing": 0, "size": 100, "done": 100, "message": ""}) == "Seeding"
    assert get_row_status({"state": 1, "hashing": 1, "size": 100, "done": 50, "message": ""}) == "Checking"
    assert get_row_status({"state": 0, "hashing": 0, "size": 100, "done": 50, "message": "Missing files"}) == "Failed"
    assert format_peer_pair(2, 10) == "2/10"

def test_main_lists_transmission_profile(monkeypatch, capsys):
    class FakeConfig:
        def get_profiles(self):
            return {"tx": {"type": "transmission", "url": "http://localhost:9091", "user": "user", "password": "pass"}}

        def get_default_profile_id(self):
            return "tx"

    class FakeTransmissionClient:
        def __init__(self, url, user, password):
            self.args = (url, user, password)

        def test_connection(self):
            return "4.0"

        def get_torrents_full(self):
            return [{
                "name": "Transmission Torrent",
                "size": 100,
                "done": 50,
                "state": 1,
                "active": 1,
                "hashing": 0,
                "message": "",
                "eta": 60,
                "seeds_connected": 2,
                "seeds_total": 5,
                "leechers_connected": 1,
                "leechers_total": 4,
            }]

    monkeypatch.setattr("list_torrents.ConfigManager", FakeConfig)
    monkeypatch.setattr("list_torrents.TransmissionClient", FakeTransmissionClient)

    main()

    out = capsys.readouterr().out
    assert "Connecting to Transmission" in out
    assert "Transmission Torrent" in out
    assert "2/5" in out
    assert "1/4" in out
