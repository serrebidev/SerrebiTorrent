import inspect
import os

import pytest

wx = pytest.importorskip("wx")

import main


def test_seed_save_path_for_file_uses_parent(tmp_path):
    source = tmp_path / "file.txt"
    source.write_bytes(b"data")

    assert main.seed_save_path_for_source(str(source)) == str(tmp_path)


def test_seed_save_path_for_folder_uses_parent(tmp_path):
    source = tmp_path / "payload"
    source.mkdir()

    assert main.seed_save_path_for_source(str(source)) == str(tmp_path)


def test_created_torrent_add_uses_source_parent_as_save_path():
    source = inspect.getsource(main.MainFrame.on_create_torrent)

    assert "seed_save_path_for_source(source_path)" in source
    assert "seed_save_path," in source


def test_clamp_rss_interval():
    assert main.clamp_rss_interval(0) == 5
    assert main.clamp_rss_interval("abc") == 300
    assert main.clamp_rss_interval(999999) == 86400
    assert main.clamp_rss_interval(600) == 600
