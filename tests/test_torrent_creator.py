import os
import tempfile
from urllib.parse import parse_qs, urlparse

import pytest

import torrent_creator
import torrent_parsing


@pytest.mark.skipif(torrent_creator.lt is None, reason="libtorrent not installed")
def test_create_torrent_bytes_roundtrip():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = os.path.join(tmp_dir, "file.txt")
        with open(src, "wb") as f:
            f.write(b"hello world")

        torrent_bytes, magnet, info_hash = torrent_creator.create_torrent_bytes(
            src,
            trackers=[],
        )

        assert torrent_bytes
        assert info_hash
        query = parse_qs(urlparse(magnet).query)
        assert f"urn:btih:{info_hash}" in query["xt"]
        assert any(xt.startswith("urn:btmh:1220") for xt in query["xt"])
        assert torrent_parsing.safe_torrent_info_hash(torrent_bytes) == info_hash


@pytest.mark.skipif(torrent_creator.lt is None, reason="libtorrent not installed")
def test_create_torrent_bytes_folder_roundtrip():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_dir = os.path.join(tmp_dir, "payload")
        os.mkdir(src_dir)
        with open(os.path.join(src_dir, "file.txt"), "wb") as f:
            f.write(b"hello world")

        torrent_bytes, magnet, info_hash = torrent_creator.create_torrent_bytes(
            src_dir,
            trackers=[],
        )

        info = torrent_creator.lt.torrent_info(torrent_bytes)
        assert torrent_bytes
        assert info_hash
        query = parse_qs(urlparse(magnet).query)
        assert f"urn:btih:{info_hash}" in query["xt"]
        assert info.name() == "payload"
        assert info.files().file_path(0).replace("\\", "/") == "payload/file.txt"


@pytest.mark.skipif(torrent_creator.lt is None, reason="libtorrent not installed")
def test_create_torrent_magnet_includes_trackers():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = os.path.join(tmp_dir, "file.txt")
        with open(src, "wb") as f:
            f.write(b"hello world")

        _, magnet, _ = torrent_creator.create_torrent_bytes(
            src,
            trackers=[
                "udp://tracker.example:1337/announce",
                "https://tracker.example/announce",
            ],
        )

        query = parse_qs(urlparse(magnet).query)
        assert query["tr"] == [
            "udp://tracker.example:1337/announce",
            "https://tracker.example/announce",
        ]


@pytest.mark.skipif(torrent_creator.lt is None, reason="libtorrent not installed")
def test_create_torrent_source_field_is_parseable():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src = os.path.join(tmp_dir, "file.txt")
        with open(src, "wb") as f:
            f.write(b"hello world")

        torrent_bytes, _, _ = torrent_creator.create_torrent_bytes(
            src,
            trackers=[],
            source="private-source",
        )

        decoded = torrent_creator.lt.bdecode(torrent_bytes)
        info = decoded.get(b"info", decoded.get("info"))
        source = info.get(b"source", info.get("source"))
        if isinstance(source, bytes):
            source = source.decode("utf-8")
        assert source == "private-source"
        assert torrent_creator.lt.torrent_info(torrent_bytes)


def test_include_torrent_path_rejects_symlink():
    with tempfile.TemporaryDirectory() as tmp_dir:
        target = os.path.join(tmp_dir, "target.txt")
        link = os.path.join(tmp_dir, "link.txt")
        with open(target, "wb") as f:
            f.write(b"hello")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as e:
            pytest.skip(f"symlink creation unavailable: {e}")

        assert torrent_creator._include_torrent_path(target) is True
        assert torrent_creator._include_torrent_path(link) is False


@pytest.mark.skipif(torrent_creator.lt is None, reason="libtorrent not installed")
def test_create_torrent_bytes_missing_path():
    with pytest.raises(FileNotFoundError):
        torrent_creator.create_torrent_bytes("does_not_exist", trackers=[])
