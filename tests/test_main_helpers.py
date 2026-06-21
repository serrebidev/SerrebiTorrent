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


def test_rss_auto_add_validates_http_links_before_client_call():
    source = inspect.getsource(main.RSSPanel._update_feed)

    assert "validate_public_torrent_url(link)" in source
    assert "client.add_torrent_url(link)" in source


def test_column_sort_preserves_selection_by_hash():
    source = inspect.getsource(main.TorrentListCtrl.on_col_click)

    assert "selected_hashes = set(self.get_selected_hashes())" in source
    assert "self._apply_sort()" in source
    assert "self.Select(idx, row.get('hash') in selected_hashes)" in source


def test_file_priority_worker_uses_captured_client_generation():
    set_source = inspect.getsource(main.TorrentDetailsPanel.set_priority)
    worker_source = inspect.getsource(main.TorrentDetailsPanel._set_priority_bg)

    assert "client = self.frame.client" in set_source
    assert "generation = self.frame.client_generation" in set_source
    assert "self._set_priority_bg, client, generation, info_hash" in set_source
    assert "client.set_file_priority(info_hash, idx, priority)" in worker_source
    assert "self._fetch_files(client, generation, info_hash)" in worker_source


def test_rss_adds_use_captured_client_generation_and_validate_manual_downloads():
    submit_source = inspect.getsource(main.RSSPanel._submit_feed_update)
    update_source = inspect.getsource(main.RSSPanel._update_feed)
    manual_source = inspect.getsource(main.RSSPanel.download_article)

    assert "self.frame.client_generation" in submit_source
    assert "client and generation == self.frame.client_generation" in update_source
    assert "client.add_torrent_url(link)" in update_source
    assert "validate_public_torrent_url(url)" in manual_source
    assert "client.add_torrent_url(url)" in manual_source


def test_remove_worker_ignores_stale_generation_completion_and_errors():
    source = inspect.getsource(main.MainFrame._remove_background)

    assert source.count("generation != self.client_generation") >= 2
    assert "if generation == self.client_generation:" in source
    assert "wx.CallAfter(self._on_action_complete" in source
