import binascii
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import clients


class FakeQbittorrentApiClient:
    def __init__(self, host=None, username=None, password=None):
        self.calls = []
        self.deleted = set()

    def auth_log_in(self):
        return None

    def _hash_list(self, torrent_hashes):
        if torrent_hashes is None:
            return []
        if isinstance(torrent_hashes, str):
            return torrent_hashes.split("|")
        return list(torrent_hashes)

    def torrents_info(self, torrent_hashes=None):
        return [
            SimpleNamespace(hash=h)
            for h in self._hash_list(torrent_hashes)
            if h.lower() not in self.deleted
        ]

    def torrents_start(self, torrent_hashes=None):
        self.calls.append(("start", torrent_hashes))

    def torrents_stop(self, torrent_hashes=None):
        self.calls.append(("stop", torrent_hashes))

    def torrents_delete(self, torrent_hashes=None, delete_files=False):
        self.calls.append((torrent_hashes, delete_files))
        self.deleted.update(h.lower() for h in self._hash_list(torrent_hashes))


class FakeQbittorrentMissingClient(FakeQbittorrentApiClient):
    def torrents_info(self, torrent_hashes=None):
        return []


class FakeQbittorrentStickyClient(FakeQbittorrentApiClient):
    def torrents_delete(self, torrent_hashes=None, delete_files=False):
        self.calls.append((torrent_hashes, delete_files))


class FakeTransmissionApiClient:
    def __init__(self, host=None, port=None, username=None, password=None, protocol=None, path=None):
        self.calls = []

    def remove_torrent(self, torrent_id, delete_data=False):
        self.calls.append((torrent_id, delete_data))


class FakeSession:
    def __init__(self):
        self.calls = []

    def remove_torrent(self, info_hash, delete_files=False):
        self.calls.append((info_hash, delete_files))


class RemoveTorrentsTests(unittest.TestCase):
    def test_qbittorrent_remove_torrents_normalizes_bytes_and_delete_flag(self):
        hash_bytes = b"0123456789abcdef0123456789abcdef01234567"
        with mock.patch.object(clients.qbittorrentapi, "Client", FakeQbittorrentApiClient):
            client = clients.QBittorrentClient("localhost", "user", "pass")
            client.remove_torrents([hash_bytes], df="false")

            self.assertEqual(len(client.c.calls), 1)
            torrent_hashes, delete_files = client.c.calls[0]
            self.assertEqual(torrent_hashes, [hash_bytes.decode("ascii")])
            self.assertFalse(delete_files)

    def test_qbittorrent_single_remove_methods_normalize_hashes(self):
        hash_bytes = b"0123456789abcdef0123456789abcdef01234567"
        hash_bytes2 = b"fedcba9876543210fedcba9876543210fedcba98"
        with mock.patch.object(clients.qbittorrentapi, "Client", FakeQbittorrentApiClient):
            client = clients.QBittorrentClient("localhost", "user", "pass")
            client.remove_torrent(hash_bytes)
            client.remove_torrent_with_data(hash_bytes2)

            self.assertEqual(
                client.c.calls,
                [
                    ([hash_bytes.decode("ascii")], False),
                    ([hash_bytes2.decode("ascii")], True),
                ],
            )

    def test_qbittorrent_remove_raises_when_hash_is_absent(self):
        with mock.patch.object(clients.qbittorrentapi, "Client", FakeQbittorrentMissingClient):
            client = clients.QBittorrentClient("localhost", "user", "pass")

            with self.assertRaisesRegex(RuntimeError, "no matching torrent"):
                client.remove_torrent("0" * 40)

            self.assertEqual(client.c.calls, [])

    def test_qbittorrent_remove_raises_when_hash_remains_after_delete(self):
        with mock.patch.object(clients.qbittorrentapi, "Client", FakeQbittorrentStickyClient):
            client = clients.QBittorrentClient("localhost", "user", "pass")
            client._DELETE_VERIFY_ATTEMPTS = 1

            with self.assertRaisesRegex(RuntimeError, "did not remove"):
                client.remove_torrent("0" * 40)

            self.assertEqual(client.c.calls, [(["0" * 40], False)])

    def test_qbittorrent_start_stop_use_v5_methods_and_normalize_hashes(self):
        hash_bytes = b"0123456789abcdef0123456789abcdef01234567"
        with mock.patch.object(clients.qbittorrentapi, "Client", FakeQbittorrentApiClient):
            client = clients.QBittorrentClient("localhost", "user", "pass")
            client.start_torrent(hash_bytes)
            client.stop_torrent(hash_bytes)

            self.assertEqual(
                client.c.calls,
                [
                    ("start", hash_bytes.decode("ascii")),
                    ("stop", hash_bytes.decode("ascii")),
                ],
            )

    def test_qbittorrent_remove_multiple_torrents_efficiently(self):
        h1 = "0000000000000000000000000000000000000001"
        h2 = "0000000000000000000000000000000000000002"
        with mock.patch.object(clients.qbittorrentapi, "Client", FakeQbittorrentApiClient):
            client = clients.QBittorrentClient("localhost", "user", "pass")
            client.remove_torrents([h1, h2], df=True)

            # Should be a single call with a list of hashes
            self.assertEqual(len(client.c.calls), 1)
            hashes, delete_files = client.c.calls[0]
            self.assertEqual(hashes, [h1, h2])
            self.assertTrue(delete_files)

    def test_transmission_remove_torrents_parses_delete_flag(self):
        with mock.patch.object(clients, "TransClient", FakeTransmissionApiClient):
            client = clients.TransmissionClient("http://localhost:9091", "user", "pass")
            client.remove_torrents(["abc123"], df="false")

            self.assertEqual(client.c.calls, [("abc123", False)])

    def test_local_remove_torrents_normalizes_raw_hash_and_delete_flag(self):
        raw_hash = b"\x01" * 20
        expected_hash = binascii.hexlify(raw_hash).decode("ascii")
        fake_session = FakeSession()

        class FakeSessionManager:
            @classmethod
            def get_instance(cls):
                return fake_session

        with mock.patch.object(clients, "SessionManager", FakeSessionManager), \
            mock.patch.object(clients, "lt", object()):
            with tempfile.TemporaryDirectory() as temp_dir:
                client = clients.LocalClient(temp_dir)
                client.remove_torrents([raw_hash], df="false")

        self.assertEqual(fake_session.calls, [(expected_hash, False)])

    def test_local_torrent_rows_use_session_canonical_hash(self):
        v1_hash = "0ecb0b05fa9334995a9b71373c4a31ed519ab5ff"

        fake_status = SimpleNamespace(
            paused=False,
            auto_managed=True,
            state=3,
            name="Hybrid torrent",
            total_wanted=10,
            total_wanted_done=0,
            all_time_upload=0,
            all_time_download=0,
            download_payload_rate=0,
            upload_payload_rate=0,
            errc=None,
            num_seeds=0,
            num_complete=0,
            num_peers=0,
            num_connections=0,
            num_incomplete=0,
            current_tracker="",
            save_path="C:\\Downloads",
        )
        fake_handle = SimpleNamespace(
            is_valid=lambda: True,
            status=lambda: fake_status,
        )

        class FakeSessionManager:
            @classmethod
            def get_instance(cls):
                return cls()

            def get_torrents(self):
                return [fake_handle]

            def _handle_hash_key(self, handle):
                return v1_hash

        fake_lt = SimpleNamespace(
            version="test",
            torrent_status=SimpleNamespace(
                seeding=5,
                finished=4,
                checking_files=1,
                queued_for_checking=0,
            ),
        )

        with mock.patch.object(clients, "SessionManager", FakeSessionManager), \
            mock.patch.object(clients, "lt", fake_lt):
            with tempfile.TemporaryDirectory() as temp_dir:
                client = clients.LocalClient(temp_dir)
                rows = client.get_torrents_full()

        self.assertEqual(rows[0]["hash"], v1_hash)


if __name__ == "__main__":
    unittest.main()
