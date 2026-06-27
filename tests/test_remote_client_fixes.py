import pytest

import clients


class FakeRTorrentD:
    def __init__(self):
        self.erase_calls = []
        self.calls = []

    def multicall2(self, *args):
        return [[
            "a" * 40,
            50,
            5,
            1000,
            1,
            1,
            0,
            "",
            5,
            2,
            "Test",
            100,
            50,
            "seed",   # d.connection_seed: string constant, NOT a peer count
            "leech",  # d.connection_leech: string constant, NOT a peer count
            10,       # d.peers_complete: seeders
            12,       # d.peers_accounted: leechers
            "C:\\Downloads",
        ]]

    def open(self, h):
        self.calls.append(("open", h))

    def start(self, h):
        self.calls.append(("start", h))

    def stop(self, h):
        self.calls.append(("stop", h))

    def close(self, h):
        self.calls.append(("close", h))

    def erase(self, h):
        self.erase_calls.append(h)
        self.calls.append(("erase", h))

    def check_hash(self, h):
        self.calls.append(("check_hash", h))

    def tracker_announce(self, h):
        self.calls.append(("tracker_announce", h))


class FakeRTorrentServer:
    def __init__(self):
        self.d = FakeRTorrentD()


def test_rtorrent_seed_leecher_indices_are_mapped_correctly():
    client = clients.RTorrentClient("http://localhost/RPC2")
    client.srv = FakeRTorrentServer()

    torrents = client.get_torrents_full()

    # rTorrent exposes peers_complete (seeders) / peers_accounted (leechers) but
    # no separate connected-vs-total split, so both map to those counts. The
    # connection_seed/connection_leech columns are string constants ("seed"/
    # "leech") and must never be read as peer counts.
    assert torrents[0]["seeds_connected"] == 10
    assert torrents[0]["leechers_connected"] == 12
    assert torrents[0]["seeds_total"] == 10
    assert torrents[0]["leechers_total"] == 12


def test_rtorrent_remove_with_data_is_unsupported():
    client = clients.RTorrentClient("http://localhost/RPC2")
    client.srv = FakeRTorrentServer()

    with pytest.raises(NotImplementedError):
        client.remove_torrent_with_data("a" * 40)

    assert client.srv.d.erase_calls == []


def test_rtorrent_actions_normalize_raw_hash_bytes():
    raw_hash = b"\x04" * 20
    expected_hash = raw_hash.hex()
    client = clients.RTorrentClient("http://localhost/RPC2")
    client.srv = FakeRTorrentServer()

    client.start_torrent(raw_hash)
    client.stop_torrent(raw_hash)
    client.remove_torrent(raw_hash)
    client.recheck_torrent(raw_hash)
    client.reannounce_torrent(raw_hash)

    assert client.srv.d.calls == [
        ("open", expected_hash),
        ("start", expected_hash),
        ("stop", expected_hash),
        ("close", expected_hash),
        ("erase", expected_hash),
        ("check_hash", expected_hash),
        ("tracker_announce", expected_hash),
    ]


def test_rtorrent_set_preferences_propagates_rpc_errors():
    class FailingServer:
        def __getattr__(self, name):
            def fail(*args):
                raise RuntimeError("rpc failed")
            return fail

    client = clients.RTorrentClient("http://localhost/RPC2")
    client.srv = FailingServer()

    with pytest.raises(RuntimeError, match="rpc failed"):
        client.set_app_preferences({"dl_limit": 100})
