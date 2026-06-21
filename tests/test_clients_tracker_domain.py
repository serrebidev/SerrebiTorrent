import clients


class FakeQbitTorrent:
    def __init__(self, tracker, state="downloading"):
        self.hash = "a" * 40
        self.name = "Test"
        self.total_size = 100
        self.completed = 50
        self.uploaded = 0
        self.ratio = 0.0
        self.state = state
        self.dlspeed = 0
        self.upspeed = 0
        self.tracker = tracker
        self.eta = -1
        self.num_seeds = 0
        self.num_complete = 0
        self.num_leechs = 0
        self.num_incomplete = 0
        self.availability = None
        self.save_path = "C:\\Downloads"


class FakeQbittorrentApiClient:
    def __init__(self, host=None, username=None, password=None):
        pass

    def auth_log_in(self):
        return None

    def torrents_info(self):
        return [
            FakeQbitTorrent(None),
            FakeQbitTorrent("http://tracker.example/announce"),
        ]


class FakeQbittorrentFailureClient(FakeQbittorrentApiClient):
    def torrents_info(self):
        return [
            FakeQbitTorrent(None, state="error"),
            FakeQbitTorrent(None, state="missingFiles"),
        ]


class FakeQbittorrentStateClient(FakeQbittorrentApiClient):
    def torrents_info(self):
        return [
            FakeQbitTorrent(None, state="forcedMetaDL"),
            FakeQbitTorrent(None, state="stoppedDL"),
        ]


class FakeTransTracker:
    def __init__(self, announce):
        self.announce = announce


class FakeTransTorrent:
    def __init__(self, trackers):
        self.status = "downloading"
        self.hashString = "b" * 40
        self.name = "Test"
        self.total_size = 100
        self.downloaded_ever = 50
        self.uploaded_ever = 0
        self.ratio = 0.0
        self.error_string = ""
        self.rate_download = 0
        self.rate_upload = 0
        self.trackers = trackers
        self.eta = -1
        self.peersSendingToUs = 0
        self.seeders = 0
        self.peersGettingFromUs = 0
        self.leechers = 0
        self.download_dir = "C:\\Downloads"


class FakeTransClient:
    def __init__(self, host=None, port=None, username=None, password=None, protocol=None, path=None):
        pass

    def get_torrents(self):
        return [
            FakeTransTorrent([]),
            FakeTransTorrent([FakeTransTracker("http://tracker.example/announce")]),
        ]


def test_qbittorrent_tracker_domain_handles_missing_tracker(monkeypatch):
    monkeypatch.setattr(clients.qbittorrentapi, "Client", FakeQbittorrentApiClient)
    client = clients.QBittorrentClient("localhost", "user", "pass")
    torrents = client.get_torrents_full()
    assert torrents[0]["tracker_domain"] == ""
    assert torrents[1]["tracker_domain"] == "tracker.example"


def test_qbittorrent_error_states_surface_as_failed(monkeypatch):
    monkeypatch.setattr(clients.qbittorrentapi, "Client", FakeQbittorrentFailureClient)
    client = clients.QBittorrentClient("localhost", "user", "pass")
    torrents = client.get_torrents_full()
    assert torrents[0]["message"] == "Error"
    assert torrents[1]["message"] == "Missing files"


def test_qbittorrent_v5_states_are_normalized(monkeypatch):
    monkeypatch.setattr(clients.qbittorrentapi, "Client", FakeQbittorrentStateClient)
    client = clients.QBittorrentClient("localhost", "user", "pass")
    torrents = client.get_torrents_full()

    assert torrents[0]["state"] == 1
    assert torrents[0]["active"] == 1
    assert torrents[1]["state"] == 0
    assert torrents[1]["active"] == 0


def test_transmission_tracker_domain_handles_empty_trackers(monkeypatch):
    monkeypatch.setattr(clients, "TransClient", FakeTransClient)
    client = clients.TransmissionClient("http://localhost:9091", "user", "pass")
    torrents = client.get_torrents_full()
    assert torrents[0]["tracker_domain"] == ""
    assert torrents[1]["tracker_domain"] == "tracker.example"
