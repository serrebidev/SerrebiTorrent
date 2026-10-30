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


def test_transmission_url_normalizes_web_ui_and_root_addresses():
    # Issue #416: pasting the browser (web UI) address, a bare host root, or
    # a trailing-slash RPC address made RPC POSTs land on an HTML page and
    # fail with "failed to parse response as json".
    cases = [
        ("http://nas.example", "/transmission/rpc"),
        ("http://nas.example:9091/", "/transmission/rpc"),
        ("http://nas.example:9091/transmission/web/", "/transmission/rpc"),
        ("http://nas.example:9091/transmission/web", "/transmission/rpc"),
        ("http://nas.example:9091/transmission", "/transmission/rpc"),
        ("http://nas.example:9091/transmission/rpc/", "/transmission/rpc"),
        ("http://nas.example:9091/proxy/transmission/web/", "/proxy/transmission/rpc"),
    ]
    for url, expected_path in cases:
        RecordingTransClient.calls = []
        with mock.patch.object(clients, "TransClient", RecordingTransClient):
            clients.TransmissionClient(url, "user", "pass")
        assert RecordingTransClient.calls[0]["path"] == expected_path, url


def test_transmission_non_json_response_gets_actionable_error():
    class HtmlTransClient:
        def __init__(self, **kwargs):
            error = ValueError("failed to parse response as json")
            error.raw_response = "<html><title>Synology DSM</title></html>"
            raise error

    with mock.patch.object(clients, "TransClient", HtmlTransClient):
        try:
            clients.TransmissionClient("http://nas.example:5000/transmission/rpc", "user", "pass")
        except ConnectionError as e:
            message = str(e)
        else:
            raise AssertionError("expected ConnectionError")
    assert "did not return RPC JSON" in message
    assert "nas.example:5000/transmission/rpc" in message
    assert "Synology DSM" in message


def test_transmission_get_files_with_real_rpc_torrent_object():
    # Issue #418: the Files tab was empty against a real Transmission
    # server. transmission_rpc's Torrent has no ".files" attribute (the
    # raw list lives in its fields / .get()), so _field() must fall back
    # to the container's raw access. The dict-based fakes above masked
    # this, so this test uses a real Torrent object.
    from transmission_rpc.torrent import Torrent

    real_torrent = Torrent(fields={
        "id": 1,
        "hashString": "a" * 40,
        "files": [
            {"name": "a.bin", "length": 100, "bytesCompleted": 50},
            {"name": "dir/b.mkv", "length": 300, "bytesCompleted": 300},
        ],
        "fileStats": [
            {"wanted": True, "priority": 1, "bytesCompleted": 50},
            {"wanted": False, "priority": -1, "bytesCompleted": 300},
        ],
    })

    class RealTorrentTransClient:
        def __init__(self, **kwargs):
            pass

        def get_torrent(self, torrent_id, arguments=None):
            assert arguments == ['files', 'fileStats']
            return real_torrent

    with mock.patch.object(clients, "TransClient", RealTorrentTransClient):
        client = clients.TransmissionClient("http://localhost:9091", "user", "pass")
        files = client.get_files("a" * 40)

    assert files == [
        {"index": 0, "name": "a.bin", "size": 100, "progress": 0.5, "priority": 2},
        {"index": 1, "name": "dir/b.mkv", "size": 300, "progress": 1.0, "priority": 0},
    ]


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
