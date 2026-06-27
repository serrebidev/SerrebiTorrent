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


def test_details_follow_focused_torrent_for_keyboard_navigation():
    init_source = inspect.getsource(main.MainFrame.__init__)
    helper_source = inspect.getsource(main.MainFrame._get_detail_hash)

    assert "wx.EVT_LIST_ITEM_FOCUSED" in init_source
    assert "active_torrent_hash_for_details(self.torrent_list)" in helper_source


def test_file_priority_worker_uses_captured_client_generation():
    set_source = inspect.getsource(main.TorrentDetailsPanel.set_priority)
    worker_source = inspect.getsource(main.TorrentDetailsPanel._set_priority_bg)

    assert "client = self.frame.client" in set_source
    assert "generation = self.frame.client_generation" in set_source
    assert "self._set_priority_bg, client, generation, info_hash" in set_source
    assert "client.set_file_priority(info_hash, idx, priority)" in worker_source
    assert "self._fetch_files(client, generation, info_hash, key)" in worker_source


def test_detail_refresh_has_inflight_guard():
    init_source = inspect.getsource(main.TorrentDetailsPanel.__init__)
    refresh_source = inspect.getsource(main.TorrentDetailsPanel.refresh_tab)
    fetch_source = inspect.getsource(main.TorrentDetailsPanel._fetch_files)

    assert "self._refresh_inflight = set()" in init_source
    assert "if key in self._refresh_inflight" in refresh_source
    assert "self._refresh_inflight.add(key)" in refresh_source
    assert "wx.CallAfter(self._finish_detail_refresh, key)" in fetch_source


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


def test_http_torrent_add_uses_captured_client_generation():
    add_source = inspect.getsource(main.MainFrame.on_add_url)
    download_source = inspect.getsource(main.MainFrame._download_and_add_torrent)
    show_source = inspect.getsource(main.MainFrame._show_add_after_download)

    assert "client = self.client" in add_source
    assert "generation = self.client_generation" in add_source
    assert "self._download_and_add_torrent, url, default_path, client, generation" in add_source
    assert "wx.CallAfter(self._show_add_after_download, data, default_path, client, generation)" in download_source
    assert "generation != self.client_generation" in show_source


def test_minimize_to_tray_only_hides_iconized_events():
    source = inspect.getsource(main.MainFrame.on_minimize)

    assert 'hasattr(event, "IsIconized") and not event.IsIconized()' in source
    assert "event.Skip()" in source


def test_profile_switch_clears_web_client_before_reconnect_and_on_failure():
    connect_source = inspect.getsource(main.MainFrame.connect_profile)
    complete_source = inspect.getsource(main.MainFrame._on_connect_complete)

    assert "self.client = None" in connect_source
    assert "self._update_web_ui()" in connect_source
    failure_block = complete_source[complete_source.index("if error or not client:") :]
    assert "self.client = None" in failure_block
    assert "self._update_web_ui()" in failure_block


def test_close_invalidates_workers_and_late_callbacks_are_ignored():
    init_source = inspect.getsource(main.MainFrame.__init__)
    close_source = inspect.getsource(main.MainFrame.force_close)
    complete_source = inspect.getsource(main.MainFrame._on_action_complete)
    refresh_source = inspect.getsource(main.MainFrame.refresh_data)

    assert "self._closing = False" in init_source
    assert "self._closing = True" in close_source
    assert "self.client_generation += 1" in close_source
    assert "if self._closing:" in complete_source
    assert "if self._closing:" in refresh_source


def test_refresh_data_queues_request_when_fetch_is_active():
    refresh_source = inspect.getsource(main.MainFrame.refresh_data)
    complete_source = inspect.getsource(main.MainFrame._on_refresh_complete)
    error_source = inspect.getsource(main.MainFrame._on_refresh_error)

    assert "self.refresh_pending = True" in refresh_source
    assert "self._drain_pending_refresh(generation)" in complete_source
    assert "self._drain_pending_refresh(generation)" in error_source


def test_update_install_uses_single_progress_dialog():
    start_source = inspect.getsource(main.MainFrame._start_update_install)
    worker_source = inspect.getsource(main.MainFrame._perform_update_background)
    started_source = inspect.getsource(main.MainFrame._on_update_started)

    assert "self._show_update_progress" in start_source
    assert "progress_cb=self._update_progress_callback" in worker_source
    assert "wx.MessageBox" not in started_source
    assert "wx.CallLater(800, self.force_close)" in started_source
