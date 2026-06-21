from unittest import mock
from datetime import timedelta

import clients


class FakeTorrent:
    def __init__(self, download_dir=None, downloadDir=None):
        self.download_dir = download_dir
        self.downloadDir = downloadDir


class FakeTransClient:
    def __init__(self, host=None, port=None, username=None, password=None, protocol=None, path=None):
        pass

    def get_torrent(self, torrent_id):
        return FakeTorrent(download_dir="C:\\Downloads")


class FakeTransClientFallback:
    def __init__(self, host=None, port=None, username=None, password=None, protocol=None, path=None):
        pass

    def get_torrent(self, torrent_id):
        return FakeTorrent(download_dir=None, downloadDir="C:\\Legacy")


class RecordingTransClient:
    calls = []

    def __init__(self, host=None, port=None, username=None, password=None, protocol=None, path=None):
        self.__class__.calls.append({
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "protocol": protocol,
            "path": path,
        })


class FakeTransClientDetails:
    def __init__(self, host=None, port=None, username=None, password=None, protocol=None, path=None):
        pass

    def get_torrents(self):
        return [{
            "status": "downloading",
            "hashString": "b" * 40,
            "name": "Test",
            "totalSize": 100,
            "downloadedEver": 50,
            "uploadedEver": 10,
            "ratio": 0.5,
            "errorString": "",
            "rateDownload": 5,
            "rateUpload": 2,
            "trackers": [{"announce": "http://tracker.example/announce"}],
            "trackerStats": [{"seederCount": 11, "leecherCount": 7}],
            "eta": timedelta(seconds=125),
            "peersSendingToUs": 3,
            "peersGettingFromUs": 4,
            "downloadDir": "C:\\Legacy",
        }]

    def get_torrent(self, torrent_id, arguments=None):
        if arguments == ['files', 'fileStats']:
            return {
                "files": [{"name": "a.bin", "length": 100, "bytesCompleted": 50}],
                "file_stats": [{"wanted": True, "priority": 1}],
            }
        if arguments == ['peers']:
            return {
                "peers": {
                    "1.2.3.4:51413": {
                        "clientName": "Transmission peer",
                        "progress": 0.5,
                        "rateToClient": 10,
                        "rateFromClient": 20,
                    }
                }
            }
        if arguments == ['trackerStats']:
            return {
                "tracker_stats": [{
                    "announce": "http://tracker.example/announce",
                    "has_announced": True,
                    "peer_count": 6,
                    "last_announce_result": "ok",
                }]
            }
        return FakeTorrent(download_dir=None, downloadDir="C:\\Legacy")


def test_transmission_save_path_prefers_download_dir():
    with mock.patch.object(clients, "TransClient", FakeTransClient):
        client = clients.TransmissionClient("http://localhost:9091", "user", "pass")
        assert client.get_torrent_save_path("abc") == "C:\\Downloads"


def test_transmission_save_path_falls_back_downloadDir():
    with mock.patch.object(clients, "TransClient", FakeTransClientFallback):
        client = clients.TransmissionClient("http://localhost:9091", "user", "pass")
        assert client.get_torrent_save_path("abc") == "C:\\Legacy"


def test_transmission_url_defaults_port_and_preserves_custom_path():
    RecordingTransClient.calls = []
    with mock.patch.object(clients, "TransClient", RecordingTransClient):
        clients.TransmissionClient("http://transmission.example/custom/rpc", "user", "pass")
    assert RecordingTransClient.calls == [{
        "host": "transmission.example",
        "port": 9091,
        "username": "user",
        "password": "pass",
        "protocol": "http",
        "path": "/custom/rpc",
    }]


def test_transmission_url_credentials_used_when_profile_fields_blank():
    RecordingTransClient.calls = []
    with mock.patch.object(clients, "TransClient", RecordingTransClient):
        clients.TransmissionClient("http://urluser:urlpass@transmission.example/custom/rpc", "", "")
    assert RecordingTransClient.calls == [{
        "host": "transmission.example",
        "port": 9091,
        "username": "urluser",
        "password": "urlpass",
        "protocol": "http",
        "path": "/custom/rpc",
    }]


def test_transmission_timedelta_eta_and_detail_model_fields():
    with mock.patch.object(clients, "TransClient", FakeTransClientDetails):
        client = clients.TransmissionClient("http://localhost:9091", "user", "pass")
        torrents = client.get_torrents_full()
        files = client.get_files("abc")
        peers = client.get_peers("abc")
        trackers = client.get_trackers("abc")

    assert torrents[0]["eta"] == 125
    assert torrents[0]["tracker_domain"] == "tracker.example"
    assert torrents[0]["seeds_connected"] == 3
    assert torrents[0]["seeds_total"] == 11
    assert torrents[0]["leechers_connected"] == 4
    assert torrents[0]["leechers_total"] == 7
    assert torrents[0]["save_path"] == "C:\\Legacy"
    assert files == [{"index": 0, "name": "a.bin", "size": 100, "progress": 0.5, "priority": 2}]
    assert peers == [{"address": "1.2.3.4:51413", "client": "Transmission peer", "progress": 0.5, "down_rate": 10, "up_rate": 20}]
    assert trackers == [{"url": "http://tracker.example/announce", "status": "Active", "peers": 6, "message": "ok"}]
