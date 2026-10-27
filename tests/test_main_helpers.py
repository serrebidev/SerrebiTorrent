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
    assert "client.add_magnet(link, None)" in source
    assert "Already added from RSS" in source


def test_desktop_torrent_file_adds_use_duplicate_guard():
    source = inspect.getsource(main.MainFrame._add_torrent_file_background)

    assert "client.add_torrent_file_if_new(" in source
    assert "self._prompt_duplicate_magnet" in source
    assert "client.add_torrent_file(data, save_path, priorities)" not in source


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
    assert "client.add_magnet(link, None)" in update_source
    assert "validate_public_torrent_url(url)" in manual_source
    assert "client.add_torrent_url(url)" in manual_source
    assert "client.add_magnet(url, None)" in manual_source


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



def test_rss_rule_toggle_uses_transactional_update_path():
    source = inspect.getsource(main.RulesManagerDialog.on_toggle)

    assert "self.manager.update_rule" in source
    assert "self.manager.save()" not in source
    assert "self._report_rule_save_failure()" in source



def test_atomic_write_bytes_replaces_destination(tmp_path):
    target = tmp_path / "created.torrent"
    target.write_bytes(b"old")

    main._atomic_write_bytes(str(target), b"new-data")

    assert target.read_bytes() == b"new-data"
    assert not list(tmp_path.glob("created.torrent.*.tmp"))


def test_atomic_write_bytes_preserves_existing_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "created.torrent"
    target.write_bytes(b"old")

    def fail_replace(_src, _dst):
        raise OSError("replace failed")

    monkeypatch.setattr(main.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        main._atomic_write_bytes(str(target), b"new-data")

    assert target.read_bytes() == b"old"
    assert not list(tmp_path.glob("created.torrent.*.tmp"))


def test_create_torrent_worker_uses_atomic_output_write():
    source = inspect.getsource(main.MainFrame.on_create_torrent)

    assert "_atomic_write_bytes(output_path, torrent_bytes)" in source



def test_manual_torrent_add_bounds_file_reads():
    source = inspect.getsource(main.MainFrame.on_add_file)

    assert "f.read(TORRENT_FILE_MAX_BYTES + 1)" in source
    assert "Torrent file exceeds the 16 MB limit." in source
    assert main.TORRENT_FILE_MAX_BYTES == 16 * 1024 * 1024



def test_cli_torrent_add_bounds_file_reads():
    source = inspect.getsource(main.MainFrame._process_cli_arg)

    assert "f.read(TORRENT_FILE_MAX_BYTES + 1)" in source
    assert "Torrent file exceeds the 16 MB limit." in source



def test_created_torrent_add_reuses_generated_bytes():
    source = inspect.getsource(main.MainFrame.on_create_torrent)

    assert 'content = result["torrent_bytes"]' in source
    add_block = source[source.index("# Optional add to client"):]
    assert 'open(output_path, "rb")' not in add_block



def test_create_torrent_reports_clipboard_failure_accurately():
    source = inspect.getsource(main.MainFrame.on_create_torrent)

    assert "clipboard_copied = self._set_clipboard_text" in source
    assert "Magnet could not be copied to clipboard." in source



def test_rss_rules_list_has_accessible_name():
    source = inspect.getsource(main.RulesManagerDialog.__init__)

    assert 'self.list.SetName("RSS Rules")' in source


def test_desktop_statusbar_has_accessible_identity():
    source = inspect.getsource(main.MainFrame.__init__)

    assert 'self.statusbar.SetName("Application status")' in source
    assert 'self.statusbar.SetHelpText("Connection status and current transfer rates.")' in source



def test_rss_rules_list_has_accessible_name():
    source = inspect.getsource(main.RulesManagerDialog.__init__)

    assert 'self.list.SetName("RSS Rules")' in source



def test_rss_editor_controls_have_accessible_names():
    editor = inspect.getsource(main.RuleEditDialog.__init__)
    panel = inspect.getsource(main.RSSPanel.__init__)

    assert 'self.pattern_input.SetName("Regex Pattern")' in editor
    assert 'self.type_choice.SetName("Rule Type")' in editor
    assert 'self.check_list.SetName("Apply to Feeds")' in editor
    assert 'self.feed_list.SetName("RSS Feeds")' in panel



def test_tracker_cache_is_keyed_by_source_url():
    source = inspect.getsource(main.MainFrame.fetch_trackers)

    assert "getattr(self, '_cached_tracker_url', None) == url" in source
    assert "self._cached_tracker_url = url" in source



def test_tracker_list_download_is_bounded():
    source = inspect.getsource(main.MainFrame.fetch_trackers)

    assert "stream=True" in source
    assert "TRACKER_LIST_MAX_BYTES" in source
    assert "iter_content(64 * 1024)" in source
    assert "Tracker list exceeds the 4 MB limit." in source



def test_remote_manual_add_does_not_offer_unsupported_initial_file_selection():
    source = inspect.getsource(main.MainFrame.on_add_file)

    assert "selectable_files = file_list if isinstance(self.client, LocalClient) else None" in source
    assert "AddTorrentDialog(self, name, selectable_files, default_path)" in source


def test_background_add_workers_ignore_stale_profile_results():
    file_source = inspect.getsource(main.MainFrame._add_torrent_file_background)
    magnet_source = inspect.getsource(main.MainFrame._add_magnet_background)

    assert file_source.count("generation != self.client_generation") >= 2
    assert "generation == self.client_generation and not self._closing" in file_source
    assert magnet_source.count("generation != self.client_generation") >= 2
    assert "generation == self.client_generation and not self._closing" in magnet_source


def test_remote_preference_workers_ignore_stale_profile_results():
    fetch_source = inspect.getsource(main.MainFrame._fetch_remote_preferences)
    apply_source = inspect.getsource(main.MainFrame._apply_remote_preferences)

    assert "generation == self.client_generation and not self._closing" in fetch_source
    assert apply_source.count("generation != self.client_generation") >= 2
    assert "not self._closing" in apply_source


def test_remaining_background_workers_ignore_stale_profile_results():
    search_source = inspect.getsource(main.MainFrame._add_search_result_background)
    download_source = inspect.getsource(main.MainFrame._download_and_add_torrent)
    auto_source = inspect.getsource(main.MainFrame._auto_start_hashes)
    bulk_source = inspect.getsource(main.MainFrame._apply_background_bulk)

    assert search_source.count("generation != self.client_generation") >= 2
    assert "generation == self.client_generation and not self._closing" in search_source
    assert "generation is not None and generation != self.client_generation" in download_source
    assert "not self._closing" in download_source
    assert auto_source.count("generation != self.client_generation") >= 2
    assert "generation == self.client_generation and not self._closing" in auto_source
    assert "generation != self.client_generation or self._closing" in bulk_source


def test_start_stop_all_capture_client_generation():
    start_source = inspect.getsource(main.MainFrame.start_all_torrents)
    stop_source = inspect.getsource(main.MainFrame.stop_all_torrents)

    assert "'Start all', self.client_generation" in start_source
    assert "'Stop all', self.client_generation" in stop_source


def test_failed_profile_connection_clears_current_profile_marker():
    source = inspect.getsource(main.MainFrame._on_connect_complete)
    failure_block = source[source.index("if error or not client:"):]

    assert "self.current_profile_id = None" in failure_block


def test_connection_manager_buttons_have_keyboard_mnemonics():
    source = inspect.getsource(main.ConnectDialog.__init__)

    for label in ("&Add", "&Edit", "&Delete", "Set De&fault", "&Connect", "C&lose"):
        assert f'label="{label}"' in source
    assert 'close_btn.SetName("Close connection manager")' in source
