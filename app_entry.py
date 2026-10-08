# Copyright (c) serrebidev and contributors
# SPDX-License-Identifier: MIT

"""Localized application entry point.

This keeps the legacy MainFrame logic intact while wiring the extracted,
tested localization/accessibility modules into the running application.
"""

from __future__ import annotations

import sys

import wx
import wx.adv

from external_catalog_runtime import install_external_catalogs

# External PO catalogs must be registered before localized modules import
# normalize_language/translation helpers into their own module namespaces.
install_external_catalogs()

import main as legacy
import watch_folder
from activity_history import ActivityHistory
from completion_notifications import CompletionTracker
from add_torrent_dialog import AddTorrentDialog as LocalizedAddTorrentDialog
from connection_dialog import ConnectDialog
from main_ui_i18n import sidebar_label, tr_main
from preferences_dialog import PreferencesDialog
from recent_save_paths import RecentSavePaths
from runtime_actions_i18n import register_associations
from torrent_list import TorrentListCtrl as LocalizedTorrentListCtrl
from torrent_diagnostics import diagnose_torrent
from torrent_parsing import torrent_required_bytes
from disk_space_guard import active_download_groups
from torrent_categories import TorrentCategoryStore

# The legacy handlers resolve AddTorrentDialog from main.py at call time. Point
# that name at the localized implementation without editing the maintainer's
# reviewed main.py.
legacy.AddTorrentDialog = LocalizedAddTorrentDialog


class ActivityHistoryDialog(wx.Dialog):
    def __init__(self, parent, history, translate):
        super().__init__(parent, title=translate("Activity History"), size=(760, 460))
        self.history = history
        self._ = translate

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(panel, label=self._("Recent activity, newest first:"))
        sizer.Add(label, 0, wx.ALL, 8)

        self.activity_list = wx.ListBox(panel)
        self.activity_list.SetName(self._("Activity History"))
        sizer.Add(self.activity_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        clear_button = wx.Button(panel, label=self._("Clear History"))
        clear_button.SetName(self._("Clear History"))
        clear_button.Bind(wx.EVT_BUTTON, self.on_clear)
        buttons.Add(clear_button, 0, wx.RIGHT, 8)

        close_button = wx.Button(panel, wx.ID_CLOSE, label=self._("Close"))
        close_button.SetName(self._("Close"))
        close_button.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(wx.ID_CLOSE))
        close_button.SetDefault()
        buttons.Add(close_button, 0)

        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        panel.SetSizer(sizer)

        top = wx.BoxSizer(wx.VERTICAL)
        top.Add(panel, 1, wx.EXPAND)
        self.SetSizer(top)
        self._reload()

    def _reload(self):
        self.activity_list.Clear()
        entries = list(reversed(self.history.entries()))
        for entry in entries:
            timestamp = entry["timestamp"].replace("T", " ", 1)
            self.activity_list.Append(
                f'{timestamp} — {entry["message"]}'
            )
        if self.activity_list.GetCount():
            self.activity_list.SetSelection(0)
            self.activity_list.SetFocus()

    def on_clear(self, event):
        result = wx.MessageBox(
            self._("Clear the activity history?"),
            self._("Activity History"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if result != wx.YES:
            return
        self.history.clear()
        self._reload()


class TorrentRateLimitDialog(wx.Dialog):
    def __init__(self, parent, translate):
        super().__init__(parent, title=translate("Set Torrent Speed Limits"))
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(
            wx.StaticText(
                panel,
                label=translate("Enter bytes per second. Use 0 for unlimited."),
            ),
            0,
            wx.ALL,
            8,
        )

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        download_label = translate("Download limit (bytes/s):")
        grid.Add(wx.StaticText(panel, label=download_label), 0, wx.ALIGN_CENTER_VERTICAL)
        self.download_limit = wx.SpinCtrl(panel, min=0, max=1000000000, initial=0)
        self.download_limit.SetName(download_label)
        grid.Add(self.download_limit, 1, wx.EXPAND)

        upload_label = translate("Upload limit (bytes/s):")
        grid.Add(wx.StaticText(panel, label=upload_label), 0, wx.ALIGN_CENTER_VERTICAL)
        self.upload_limit = wx.SpinCtrl(panel, min=0, max=1000000000, initial=0)
        self.upload_limit.SetName(upload_label)
        grid.Add(self.upload_limit, 1, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(sizer)
        top = wx.BoxSizer(wx.VERTICAL)
        top.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(top)
        self.download_limit.SetFocus()

    def get_limits(self):
        return self.download_limit.GetValue(), self.upload_limit.GetValue()


class LocalizedMainFrame(legacy.MainFrame):
    """Main frame with localized menus, sidebar and extracted dialogs."""

    def _language(self):
        return self.config_manager.get_preferences().get("language", "system")

    def _(self, text):
        return tr_main(text, self._language())

    def __init__(self):
        self._completion_tracker = CompletionTracker()
        self.activity_history = ActivityHistory()
        self.recent_save_paths = RecentSavePaths()
        self.torrent_categories = TorrentCategoryStore()
        self.category_items = {}
        self._ratio_pause_pending = set()
        self._disk_space_guard_busy = False
        self._name_filter_query = ""
        super().__init__()
        self.categories_root = self.sidebar.AppendItem(
            self.root_id,
            self._("Torrent Categories"),
        )
        self._install_localized_torrent_list()
        self._apply_localized_static_labels()
        self._watch_scan_busy = False
        self.watch_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_watch_timer, self.watch_timer)
        self.watch_timer.Start(watch_folder.SCAN_INTERVAL_SECONDS * 1000)

    def get_recent_save_paths(self):
        if not self.current_profile_id:
            return []
        return self.recent_save_paths.paths(self.current_profile_id)

    def remember_recent_save_path(self, value):
        if not self.current_profile_id:
            return
        self.recent_save_paths.remember(self.current_profile_id, value)

    def on_watch_timer(self, event):
        folder = watch_folder.clean_folder_path(self.config_manager.get_preferences().get("watch_folder"))
        if not folder or not self.client or self._watch_scan_busy or self._closing:
            return
        self._watch_scan_busy = True
        try:
            self.thread_pool.submit(
                self._watch_scan_background, self.client, self.client_generation, folder)
        except RuntimeError:
            # A busy flag left set here would stop every later scan.
            self._watch_scan_busy = False

    def _watch_scan_background(self, client, generation, folder):
        hashes = []

        def add(data):
            if generation != self.client_generation:
                raise watch_folder.RetryImportLater(self._("The active profile changed."))
            client.add_torrent_file(data, None, None)
            hash_hint = self._maybe_hash_from_torrent_bytes(data)
            if hash_hint:
                hashes.append(hash_hint)

        added, failed = [], []
        try:
            added, failed = watch_folder.import_folder(folder, add)
            if hashes and self.config_manager.get_preferences().get("auto_start", True):
                self._auto_start_hashes(generation, hashes)
        finally:
            wx.CallAfter(self._on_watch_scan_done, added, failed)

    def _on_watch_scan_done(self, added, failed):
        self._watch_scan_busy = False
        if self._closing or not (added or failed):
            return
        # Errors go to the status bar, not a dialog: this runs every minute
        # unattended, and a broken file is renamed to .failed so it stops.
        if failed:
            message = self._("Watch folder: added {added}, failed {failed} ({name}: {error})").format(
                added=len(added), failed=len(failed), name=failed[0][0], error=failed[0][1])
        else:
            message = self._("Watch folder: added {count} torrent(s)").format(count=len(added))
        self.statusbar.SetStatusText(message, 0)
        self._record_activity(message, kind="error" if failed else "success")
        self.refresh_data()

    def _install_localized_torrent_list(self):
        """Replace the empty legacy list before deferred auto-connect can populate it."""
        old_list = self.torrent_list
        new_list = LocalizedTorrentListCtrl(
            self.right_splitter,
            language=self._language(),
        )
        new_list.Bind(wx.EVT_KEY_DOWN, self.on_list_key)
        new_list.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        new_list.Bind(wx.EVT_RIGHT_DOWN, self.on_context_menu)
        new_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_torrent_selected)
        new_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_torrent_selected)
        new_list.Bind(wx.EVT_LIST_ITEM_FOCUSED, self.on_torrent_selected)

        # A new child goes last in Tab order; keep the list before the details panel.
        new_list.MoveBeforeInTabOrder(old_list)
        self.right_splitter.ReplaceWindow(old_list, new_list)
        old_list.Hide()
        self.torrent_list = new_list
        new_list.Show()
        old_list.Destroy()
        self.right_splitter.Layout()

    def _apply_localized_static_labels(self):
        language = self._language()
        if hasattr(self, "sidebar"):
            self.sidebar.SetName(tr_main("Categories", language))
            for key, item_id in getattr(self, "cat_ids", {}).items():
                self.sidebar.SetItemText(item_id, sidebar_label(key, language=language))
            if hasattr(self, "trackers_root"):
                self.sidebar.SetItemText(self.trackers_root, tr_main("Trackers", language))
            if hasattr(self, "categories_root"):
                self.sidebar.SetItemText(
                    self.categories_root,
                    tr_main("Torrent Categories", language),
                )
        if hasattr(self, "torrent_list"):
            self.torrent_list.SetName(tr_main("Torrent List", language))
        if hasattr(self, "statusbar") and not self.connected:
            self.statusbar.SetStatusText(tr_main("Disconnected", language), 0)

    def _build_menu_bar(self):
        """Build the existing menu structure with localized visible labels."""
        _ = self._
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        profiles = self.config_manager.get_profiles()
        self._connect_menu_id_to_profile = {}

        if profiles:
            connect_menu = wx.Menu()
            default_id = self.config_manager.get_default_profile_id()

            def _sort_key(kv):
                pid, profile = kv
                return str(profile.get("name", pid)).lower()

            for pid, profile in sorted(profiles.items(), key=_sort_key):
                label = str(profile.get("name") or pid)
                if default_id and pid == default_id:
                    label += f" ({_('Default')})"
                item = connect_menu.Append(wx.ID_ANY, label, _("Connect to this profile"))
                self._connect_menu_id_to_profile[item.GetId()] = pid
                self.Bind(wx.EVT_MENU, self.on_connect_profile_menu, item)

            connect_menu.AppendSeparator()
            manage_item = connect_menu.Append(
                wx.ID_ANY,
                _("Connection Manager...\tCtrl+Shift+C"),
                _("Add/edit/delete profiles and connect"),
            )
            self.Bind(wx.EVT_MENU, self.on_connect, manage_item)
            file_menu.AppendSubMenu(connect_menu, _("&Connect"), _("Connect or switch profile"))
        else:
            connect_item = file_menu.Append(
                wx.ID_ANY,
                _("&Connect...\tCtrl+Shift+C"),
                _("Manage Profiles & Connect"),
            )
            self.Bind(wx.EVT_MENU, self.on_connect, connect_item)

        add_file_item = file_menu.Append(
            wx.ID_ANY,
            _("&Add Torrent File...\tCtrl+O"),
            _("Add a torrent from a local file"),
        )
        add_url_item = file_menu.Append(
            wx.ID_ANY,
            _("Add &URL/Magnet...\tCtrl+U"),
            _("Add a torrent from a URL or Magnet link"),
        )
        create_torrent_item = file_menu.Append(
            wx.ID_ANY,
            _("Create &Torrent...\tCtrl+N"),
            _("Create a .torrent file from a file or folder"),
        )
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, _("E&xit"), _("Exit application"))
        menubar.Append(file_menu, _("&File"))

        actions_menu = wx.Menu()
        start_item = actions_menu.Append(
            wx.ID_ANY, _("&Start\tCtrl+S"), _("Start selected torrents")
        )
        pause_item = actions_menu.Append(
            wx.ID_ANY, _("&Pause\tCtrl+P"), _("Pause selected torrents")
        )
        resume_item = actions_menu.Append(
            wx.ID_ANY, _("&Resume\tCtrl+R"), _("Resume selected torrents")
        )
        start_all_item = actions_menu.Append(wx.ID_ANY, _("Start All"))
        stop_all_item = actions_menu.Append(wx.ID_ANY, _("Stop All"))
        actions_menu.AppendSeparator()
        recheck_item = actions_menu.Append(
            wx.ID_ANY,
            _("Force Re&check"),
            _("Force a recheck/verification (if supported)"),
        )
        reannounce_item = actions_menu.Append(
            wx.ID_ANY,
            _("Force Reannoun&ce"),
            _("Force an immediate tracker announce (if supported)"),
        )
        diagnose_item = actions_menu.Append(
            wx.ID_ANY,
            _("Diagnose &Torrent\tCtrl+D"),
            _("Diagnose the selected torrent"),
        )
        recover_stalled_item = actions_menu.Append(
            wx.ID_ANY,
            _("Try to &Fix Stalled Torrent\tCtrl+Shift+D"),
            _("Resume incomplete torrents and force a tracker announce"),
        )
        queue_menu = wx.Menu()
        queue_top_item = queue_menu.Append(
            wx.ID_ANY,
            _("Move to &top\tCtrl+Alt+Home"),
            _("Move selected torrents to the top of the queue"),
        )
        queue_up_item = queue_menu.Append(
            wx.ID_ANY,
            _("Move &up\tCtrl+Alt+Up"),
            _("Move selected torrents up in the queue"),
        )
        queue_down_item = queue_menu.Append(
            wx.ID_ANY,
            _("Move &down\tCtrl+Alt+Down"),
            _("Move selected torrents down in the queue"),
        )
        queue_bottom_item = queue_menu.Append(
            wx.ID_ANY,
            _("Move to &bottom\tCtrl+Alt+End"),
            _("Move selected torrents to the bottom of the queue"),
        )
        actions_menu.AppendSubMenu(
            queue_menu,
            _("Queue"),
            _("Change selected torrent queue position"),
        )
        actions_menu.AppendSeparator()
        copy_hash_item = actions_menu.Append(
            wx.ID_ANY,
            _("Copy &Info Hash\tCtrl+I"),
            _("Copy the info hash for selected torrents"),
        )
        copy_magnet_item = actions_menu.Append(
            wx.ID_ANY,
            _("Copy &Magnet Link\tCtrl+M"),
            _("Copy a magnet link for selected torrents"),
        )
        open_folder_item = actions_menu.Append(
            wx.ID_ANY,
            _("Open Download &Folder"),
            _("Open the download folder (if available)"),
        )
        move_data_item = actions_menu.Append(
            wx.ID_ANY,
            _("Move torrent &data..."),
            _("Move selected torrent data to another folder"),
        )
        rate_limits_item = actions_menu.Append(
            wx.ID_ANY,
            _("Set torrent speed &limits...\tCtrl+Alt+L"),
            _("Set download and upload limits for selected torrents"),
        )
        set_category_item = actions_menu.Append(
            wx.ID_ANY,
            _("Set &Category...\tCtrl+Alt+C"),
            _("Assign a SerrebiTorrent category to selected torrents"),
        )
        clear_category_item = actions_menu.Append(
            wx.ID_ANY,
            _("Clear Category"),
            _("Remove the SerrebiTorrent category from selected torrents"),
        )
        actions_menu.AppendSeparator()
        remove_item = actions_menu.Append(
            wx.ID_ANY, _("&Remove\tDel"), _("Remove selected torrents")
        )
        remove_data_item = actions_menu.Append(
            wx.ID_ANY,
            _("Remove with &Data\tShift+Del"),
            _("Remove selected torrents and data"),
        )
        select_all_item = actions_menu.Append(
            wx.ID_SELECTALL,
            _("Select &All\tCtrl+A"),
            _("Select all torrents"),
        )
        select_none_item = actions_menu.Append(
            wx.ID_ANY,
            _("Select &none"),
        )
        menubar.Append(actions_menu, _("&Actions"))

        tools_menu = wx.Menu()
        search_item = tools_menu.Append(
            wx.ID_ANY,
            _("&Search for Torrents...\tCtrl+F"),
            _("Search torrent indexers and add what you find"),
        )
        filter_name_item = tools_menu.Append(
            wx.ID_ANY,
            _("Filter torrent list by &name...\tCtrl+L"),
            _("Filter the current torrent list by name"),
        )
        clear_name_filter_item = tools_menu.Append(
            wx.ID_ANY,
            _("Clear torrent name filter\tCtrl+Shift+L"),
            _("Show all torrents allowed by the current sidebar filter"),
        )
        activity_history_item = tools_menu.Append(
            wx.ID_ANY,
            _("Activity &History...\tCtrl+Shift+H"),
            _("Review recent SerrebiTorrent activity"),
        )
        tools_menu.AppendSeparator()
        assoc_item = tools_menu.Append(
            wx.ID_ANY,
            _("Register &Associations"),
            _("Associate .torrent and magnet links with this app"),
        )
        update_item = tools_menu.Append(
            wx.ID_ANY,
            _("Check for &Updates...\tF5"),
            _("Check for updates"),
        )
        tools_menu.AppendSeparator()

        self.qbit_remote_prefs_item = tools_menu.Append(
            wx.ID_ANY,
            _("qBittorrent Remote &Settings..."),
            _("Edit connected qBittorrent settings"),
        )
        self.trans_remote_prefs_item = tools_menu.Append(
            wx.ID_ANY,
            _("Transmission Remote &Settings..."),
            _("Edit connected Transmission settings"),
        )
        self.rtorrent_remote_prefs_item = tools_menu.Append(
            wx.ID_ANY,
            _("rTorrent Remote &Settings..."),
            _("Edit connected rTorrent settings"),
        )
        tools_menu.AppendSeparator()
        local_settings_item = tools_menu.Append(
            wx.ID_PREFERENCES,
            _("Local Session &Settings...\tCtrl+,"),
            _("Configure local session and application settings"),
        )

        self.qbit_remote_prefs_item.Enable(False)
        self.trans_remote_prefs_item.Enable(False)
        self.rtorrent_remote_prefs_item.Enable(False)
        menubar.Append(tools_menu, _("&Tools"))

        help_menu = wx.Menu()
        about_item = help_menu.Append(
            wx.ID_ABOUT, _("&About SerrebiTorrent"), _("About this application")
        )
        menubar.Append(help_menu, _("&Help"))
        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self.on_add_file, add_file_item)
        self.Bind(wx.EVT_MENU, self.on_add_url, add_url_item)
        self.Bind(wx.EVT_MENU, self.on_create_torrent, create_torrent_item)
        self.Bind(wx.EVT_MENU, self.on_prefs, local_settings_item)
        self.Bind(wx.EVT_MENU, lambda event: self.Close(force=True), exit_item)

        self.Bind(wx.EVT_MENU, self.on_start, start_item)
        self.Bind(wx.EVT_MENU, self.on_pause, pause_item)
        self.Bind(wx.EVT_MENU, self.on_resume, resume_item)
        self.Bind(wx.EVT_MENU, lambda event: self.start_all_torrents(), start_all_item)
        self.Bind(wx.EVT_MENU, lambda event: self.stop_all_torrents(), stop_all_item)
        self.Bind(wx.EVT_MENU, self.on_recheck, recheck_item)
        self.Bind(wx.EVT_MENU, self.on_reannounce, reannounce_item)
        self.Bind(wx.EVT_MENU, self.on_diagnose_torrent, diagnose_item)
        self.Bind(wx.EVT_MENU, self.on_try_fix_stalled_torrents, recover_stalled_item)
        self.Bind(wx.EVT_MENU, self.on_queue_top, queue_top_item)
        self.Bind(wx.EVT_MENU, self.on_queue_up, queue_up_item)
        self.Bind(wx.EVT_MENU, self.on_queue_down, queue_down_item)
        self.Bind(wx.EVT_MENU, self.on_queue_bottom, queue_bottom_item)
        self.Bind(wx.EVT_MENU, self.on_copy_info_hash, copy_hash_item)
        self.Bind(wx.EVT_MENU, self.on_copy_magnet, copy_magnet_item)
        self.Bind(wx.EVT_MENU, self.on_open_download_folder, open_folder_item)
        self.Bind(wx.EVT_MENU, self.on_move_torrent_data, move_data_item)
        self.Bind(wx.EVT_MENU, self.on_set_torrent_rate_limits, rate_limits_item)
        self.Bind(wx.EVT_MENU, self.on_set_torrent_category, set_category_item)
        self.Bind(wx.EVT_MENU, self.on_clear_torrent_category, clear_category_item)
        self.Bind(wx.EVT_MENU, self.on_remove, remove_item)
        self.Bind(wx.EVT_MENU, self.on_remove_data, remove_data_item)
        self.Bind(wx.EVT_MENU, self.on_select_all, select_all_item)
        self.Bind(wx.EVT_MENU, self.on_select_none, select_none_item)

        self.Bind(wx.EVT_MENU, self.on_search_torrents, search_item)
        self.Bind(wx.EVT_MENU, self.on_filter_torrents_by_name, filter_name_item)
        self.Bind(wx.EVT_MENU, self.on_clear_torrent_name_filter, clear_name_filter_item)
        self.Bind(wx.EVT_MENU, self.on_activity_history, activity_history_item)
        self.Bind(
            wx.EVT_MENU,
            lambda event: register_associations(self._language()),
            assoc_item,
        )
        self.Bind(wx.EVT_MENU, self.on_check_updates, update_item)
        self.Bind(wx.EVT_MENU, self.on_remote_preferences, self.qbit_remote_prefs_item)
        self.Bind(wx.EVT_MENU, self.on_remote_preferences, self.trans_remote_prefs_item)
        self.Bind(wx.EVT_MENU, self.on_remote_preferences, self.rtorrent_remote_prefs_item)
        self.Bind(wx.EVT_MENU, self.on_about, about_item)

        self._update_remote_prefs_menu_state()
        accel_entries = [
            (wx.ACCEL_CTRL, ord("A"), select_all_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("A"), select_none_item.GetId()),
            (wx.ACCEL_CTRL, ord("S"), start_item.GetId()),
            (wx.ACCEL_CTRL, ord("P"), pause_item.GetId()),
            (wx.ACCEL_CTRL, ord("R"), resume_item.GetId()),
            (wx.ACCEL_CTRL, ord("D"), diagnose_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("D"), recover_stalled_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_ALT, ord("S"), start_all_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_ALT, ord("P"), stop_all_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_ALT, wx.WXK_HOME, queue_top_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_ALT, wx.WXK_UP, queue_up_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_ALT, wx.WXK_DOWN, queue_down_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_ALT, wx.WXK_END, queue_bottom_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_ALT, ord("L"), rate_limits_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_ALT, ord("C"), set_category_item.GetId()),
            (wx.ACCEL_NORMAL, wx.WXK_DELETE, remove_item.GetId()),
            (wx.ACCEL_SHIFT, wx.WXK_DELETE, remove_data_item.GetId()),
            (wx.ACCEL_CTRL, ord("O"), add_file_item.GetId()),
            (wx.ACCEL_CTRL, ord("U"), add_url_item.GetId()),
            (wx.ACCEL_CTRL, ord("N"), create_torrent_item.GetId()),
            (wx.ACCEL_CTRL, ord("I"), copy_hash_item.GetId()),
            (wx.ACCEL_CTRL, ord("M"), copy_magnet_item.GetId()),
            (wx.ACCEL_CTRL, ord(","), local_settings_item.GetId()),
            (wx.ACCEL_CTRL, ord("F"), search_item.GetId()),
            (wx.ACCEL_CTRL, ord("L"), filter_name_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("L"), clear_name_filter_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("H"), activity_history_item.GetId()),
        ]
        self.SetAcceleratorTable(wx.AcceleratorTable(accel_entries))

    def on_activity_history(self, event):
        dialog = ActivityHistoryDialog(self, self.activity_history, self._)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()

    def _record_activity(self, message, kind="info"):
        try:
            self.activity_history.append(str(message), kind=kind)
        except Exception:
            # User-facing history must never break the torrent workflow.
            pass

    def _on_action_complete(self, msg):
        self._record_activity(self._(str(msg)), kind="success")
        super()._on_action_complete(msg)

    def _on_action_error(self, msg):
        self._record_activity(self._(str(msg)), kind="error")
        super()._on_action_error(msg)

    def on_select_none(self, event):
        count = self.torrent_list.GetItemCount()
        for index in range(count):
            self.torrent_list.Select(index, False)

    def _selected_category_hashes(self):
        if not self.current_profile_id:
            self.statusbar.SetStatusText(self._("Connect to a profile first."), 0)
            return []
        hashes = self.torrent_list.get_selected_hashes()
        if not hashes:
            self.statusbar.SetStatusText(self._("No torrents selected."), 0)
            return []
        return hashes

    def on_set_torrent_category(self, event):
        hashes = self._selected_category_hashes()
        if not hashes:
            return

        existing = {
            self.torrent_categories.get(self.current_profile_id, torrent_hash)
            for torrent_hash in hashes
        }
        existing.discard("")
        initial = next(iter(existing)) if len(existing) == 1 else ""
        dialog = wx.TextEntryDialog(
            self,
            self._("Category name:"),
            self._("Set Torrent Category"),
            initial,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            category = self.torrent_categories.clean_category(dialog.GetValue())
        finally:
            dialog.Destroy()
        if not category:
            self.statusbar.SetStatusText(self._("Category name is required."), 0)
            return

        self.torrent_categories.assign_many(
            self.current_profile_id,
            hashes,
            category,
        )
        message = self._("Category set to {category} for {count} torrent(s).").format(
            category=category,
            count=len(hashes),
        )
        self.statusbar.SetStatusText(message, 0)
        self._record_activity(message, kind="success")
        self.refresh_data()

    def on_clear_torrent_category(self, event):
        hashes = self._selected_category_hashes()
        if not hashes:
            return
        self.torrent_categories.assign_many(self.current_profile_id, hashes, "")
        message = self._("Category cleared for {count} torrent(s).").format(
            count=len(hashes)
        )
        self.statusbar.SetStatusText(message, 0)
        self._record_activity(message, kind="success")
        self.refresh_data()

    def _refresh_category_sidebar(self, torrents):
        if not hasattr(self, "categories_root"):
            return
        hashes = [torrent.get("hash") for torrent in torrents if torrent.get("hash")]
        counts = self.torrent_categories.counts(self.current_profile_id, hashes)

        for category, count in counts.items():
            label = f"{category} ({count})"
            item = self.category_items.get(category)
            if item:
                self.sidebar.SetItemText(item, label)
            else:
                self.category_items[category] = self.sidebar.AppendItem(
                    self.categories_root,
                    label,
                )

        for category in list(self.category_items):
            if category not in counts:
                self.sidebar.Delete(self.category_items.pop(category))

        if counts:
            self.sidebar.Expand(self.categories_root)

    def on_filter_torrents_by_name(self, event):
        dialog = wx.TextEntryDialog(
            self,
            self._("Filter torrent list by name:"),
            self._("Filter Torrents"),
            self._name_filter_query,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self._name_filter_query = dialog.GetValue().strip()
        finally:
            dialog.Destroy()

        self.refresh_data()
        if hasattr(self, "statusbar"):
            if self._name_filter_query:
                self.statusbar.SetStatusText(
                    self._("Torrent name filter: {query}").format(
                        query=self._name_filter_query
                    ),
                    0,
                )
            else:
                self.statusbar.SetStatusText(self._("Torrent name filter cleared."), 0)

    def on_clear_torrent_name_filter(self, event):
        if not self._name_filter_query:
            return
        self._name_filter_query = ""
        self.refresh_data()
        if hasattr(self, "statusbar"):
            self.statusbar.SetStatusText(self._("Torrent name filter cleared."), 0)

    def on_prefs(self, event):
        dlg = PreferencesDialog(self, self.config_manager)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            previous_prefs = self.config_manager.get_preferences()
            prefs = dlg.get_preferences()
            try:
                self.config_manager.set_preferences(prefs)
            except Exception as exc:  # noqa: BLE001 - UI boundary
                wx.MessageBox(
                    self._("Failed to apply settings: {error}").format(error=exc),
                    "SerrebiTorrent",
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return
            session = legacy.SessionManager.get_instance()
            try:
                session.apply_preferences(prefs)
            except Exception as exc:  # noqa: BLE001 - UI boundary
                try:
                    self.config_manager.set_preferences(previous_prefs)
                except Exception:
                    pass
                try:
                    session.apply_preferences(previous_prefs)
                except Exception:
                    pass
                wx.MessageBox(
                    self._("Failed to apply settings: {error}").format(error=exc),
                    "SerrebiTorrent",
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return
            self._update_client_default_save_path()
            self._update_web_ui()
            self._schedule_auto_update_check()

            interval = legacy.clamp_rss_interval(prefs.get("rss_update_interval", 300))
            self.rss_timer.Start(interval * 1000)

            if hasattr(self, "rss_panel"):
                self.rss_panel.manager.load()
                self.rss_panel.refresh_feeds_list()
                self.rss_panel.article_list.SetItemCount(0)
                self.rss_panel.current_articles = []

            self._build_menu_bar()
            self._apply_localized_static_labels()
        finally:
            dlg.Destroy()

    def on_connect(self, event):
        dlg = ConnectDialog(self, self.config_manager)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                self.connect_profile(dlg.selected_profile_id)
        finally:
            dlg.Destroy()
        self._build_menu_bar()

    def connect_profile(self, pid):
        profile = self.config_manager.get_profile(pid)
        if not profile:
            return
        self._completion_tracker.reset()
        self._ratio_pause_pending.clear()
        self.current_filter = "All"
        for item in list(self.category_items.values()):
            try:
                self.sidebar.Delete(item)
            except Exception:
                pass
        self.category_items.clear()
        super().connect_profile(pid)
        if hasattr(self, "statusbar") and not self.connected:
            self.statusbar.SetStatusText(self._("Connecting..."), 0)

    def _on_connect_complete(self, generation, profile, client, error):
        super()._on_connect_complete(generation, profile, client, error)
        if generation != self.client_generation or not hasattr(self, "statusbar"):
            return
        if error or not client:
            self.statusbar.SetStatusText(self._("Connection Failed"), 0)
            failure_message = self._("Connection failed: {error}").format(error=error)
            self._record_activity(failure_message, kind="error")
            return
        message = self._("Connected to {name}").format(
            name=profile.get("name", self._("Profile"))
        )
        if profile.get("type") != "local":
            message += f" ({self._('Local session active')})"
        self.statusbar.SetStatusText(message, 0)
        self._record_activity(message, kind="success")

    def on_filter_change(self, event):
        """Keep canonical filter keys independent from translated sidebar labels."""
        item = event.GetItem()
        if not item.IsOk():
            return

        target_window = self.right_splitter
        if item == self.rss_id:
            target_window = self.rss_panel

        current_window = self.splitter.GetWindow2()
        if current_window != target_window:
            if current_window:
                self.splitter.ReplaceWindow(current_window, target_window)
                current_window.Hide()
            else:
                self.splitter.SplitVertically(self.sidebar, target_window, 220)
            target_window.Show()

        if item == self.rss_id:
            return
        if item == self.categories_root:
            return

        for category, item_id in self.category_items.items():
            if item == item_id:
                self.current_filter = f"category:{category}"
                self.refresh_data()
                return

        for key, item_id in self.cat_ids.items():
            if item == item_id:
                self.current_filter = key
                self.refresh_data()
                return

        text = self.sidebar.GetItemText(item)
        if "(" in text:
            text = text.rsplit(" (", 1)[0]
        self.current_filter = text
        self.refresh_data()

    def on_context_menu(self, event):
        self._prepare_torrent_context_menu_target(event)
        menu = wx.Menu()

        start = menu.Append(wx.ID_ANY, self._("Start"))
        pause = menu.Append(wx.ID_ANY, self._("Pause"))
        resume = menu.Append(wx.ID_ANY, self._("Resume"))
        menu.AppendSeparator()
        recheck = menu.Append(wx.ID_ANY, self._("Force Recheck"))
        reannounce = menu.Append(wx.ID_ANY, self._("Force Reannounce"))
        diagnose = menu.Append(wx.ID_ANY, self._("Diagnose Torrent"))
        recover_stalled = menu.Append(wx.ID_ANY, self._("Try to Fix Stalled Torrent"))
        queue_menu = wx.Menu()
        queue_top = queue_menu.Append(wx.ID_ANY, self._("Move to top"))
        queue_up = queue_menu.Append(wx.ID_ANY, self._("Move up"))
        queue_down = queue_menu.Append(wx.ID_ANY, self._("Move down"))
        queue_bottom = queue_menu.Append(wx.ID_ANY, self._("Move to bottom"))
        menu.AppendSubMenu(queue_menu, self._("Queue"))
        menu.AppendSeparator()
        copy_hash = menu.Append(wx.ID_ANY, self._("Copy Info Hash"))
        copy_magnet = menu.Append(wx.ID_ANY, self._("Copy Magnet Link"))
        open_folder = menu.Append(wx.ID_ANY, self._("Open Download Folder"))
        move_data = menu.Append(wx.ID_ANY, self._("Move torrent data..."))
        rate_limits = menu.Append(wx.ID_ANY, self._("Set torrent speed limits..."))
        set_category = menu.Append(wx.ID_ANY, self._("Set Category..."))
        clear_category = menu.Append(wx.ID_ANY, self._("Clear Category"))
        menu.AppendSeparator()
        remove = menu.Append(wx.ID_ANY, self._("Remove"))
        remove_data = menu.Append(wx.ID_ANY, self._("Remove with Data"))

        self.Bind(wx.EVT_MENU, self.on_start, start)
        self.Bind(wx.EVT_MENU, self.on_pause, pause)
        self.Bind(wx.EVT_MENU, self.on_resume, resume)
        self.Bind(wx.EVT_MENU, self.on_recheck, recheck)
        self.Bind(wx.EVT_MENU, self.on_reannounce, reannounce)
        self.Bind(wx.EVT_MENU, self.on_diagnose_torrent, diagnose)
        self.Bind(wx.EVT_MENU, self.on_try_fix_stalled_torrents, recover_stalled)
        self.Bind(wx.EVT_MENU, self.on_queue_top, queue_top)
        self.Bind(wx.EVT_MENU, self.on_queue_up, queue_up)
        self.Bind(wx.EVT_MENU, self.on_queue_down, queue_down)
        self.Bind(wx.EVT_MENU, self.on_queue_bottom, queue_bottom)
        self.Bind(wx.EVT_MENU, self.on_copy_info_hash, copy_hash)
        self.Bind(wx.EVT_MENU, self.on_copy_magnet, copy_magnet)
        self.Bind(wx.EVT_MENU, self.on_open_download_folder, open_folder)
        self.Bind(wx.EVT_MENU, self.on_move_torrent_data, move_data)
        self.Bind(wx.EVT_MENU, self.on_set_torrent_rate_limits, rate_limits)
        self.Bind(wx.EVT_MENU, self.on_set_torrent_category, set_category)
        self.Bind(wx.EVT_MENU, self.on_clear_torrent_category, clear_category)
        self.Bind(wx.EVT_MENU, self.on_remove, remove)
        self.Bind(wx.EVT_MENU, self.on_remove_data, remove_data)

        try:
            self.PopupMenu(menu)
        finally:
            menu.Destroy()

    def on_move_torrent_data(self, event):
        if not self.client:
            self.statusbar.SetStatusText(self._("Not connected to any client."), 0)
            return
        if not getattr(self.client, "supports_move_storage", False):
            self.statusbar.SetStatusText(
                self._("Moving torrent data is not supported by this client."),
                0,
            )
            return

        hashes = self.torrent_list.get_selected_hashes()
        if not hashes:
            self.statusbar.SetStatusText(self._("No torrents selected."), 0)
            return

        dialog = wx.TextEntryDialog(
            self,
            self._("Enter the destination folder for selected torrent data:"),
            self._("Move Torrent Data"),
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            destination = dialog.GetValue().strip()
        finally:
            dialog.Destroy()
        if not destination:
            self.statusbar.SetStatusText(self._("Destination folder is required."), 0)
            return

        generation = self.client_generation
        self.statusbar.SetStatusText(self._("Moving selected torrent data..."), 0)
        self.thread_pool.submit(
            self._move_torrent_data_background,
            self.client,
            hashes,
            destination,
            generation,
        )

    def _move_torrent_data_background(self, client, hashes, destination, generation):
        failed = 0
        last_error = None
        for torrent_hash in hashes:
            if generation != self.client_generation or self._closing:
                return
            try:
                client.move_torrent_data(torrent_hash, destination)
            except Exception as exc:  # noqa: BLE001 - remote client boundary
                failed += 1
                last_error = exc

        if generation != self.client_generation or self._closing:
            return
        if failed == 0:
            wx.CallAfter(
                self._on_action_complete,
                self._("Selected torrent data moved successfully."),
            )
        elif failed < len(hashes):
            wx.CallAfter(
                self.statusbar.SetStatusText,
                self._(
                    "Torrent data move completed with {failed} failure(s). Last error: {error}"
                ).format(failed=failed, error=last_error),
                0,
            )
            wx.CallAfter(self.refresh_data)
        else:
            wx.CallAfter(
                self._on_action_error,
                self._("Failed to move torrent data: {error}").format(error=last_error),
            )

    def on_set_torrent_rate_limits(self, event):
        if not self.client:
            self.statusbar.SetStatusText(self._("Not connected to any client."), 0)
            return
        if not getattr(self.client, "supports_torrent_rate_limits", False):
            self.statusbar.SetStatusText(
                self._("Per-torrent speed limits are not supported by this client."),
                0,
            )
            return

        hashes = self.torrent_list.get_selected_hashes()
        if not hashes:
            self.statusbar.SetStatusText(self._("No torrents selected."), 0)
            return

        dialog = TorrentRateLimitDialog(self, self._)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            download_limit, upload_limit = dialog.get_limits()
        finally:
            dialog.Destroy()

        generation = self.client_generation
        self.statusbar.SetStatusText(self._("Applying torrent speed limits..."), 0)
        self.thread_pool.submit(
            self._set_torrent_rate_limits_background,
            self.client,
            hashes,
            download_limit,
            upload_limit,
            generation,
        )

    def _set_torrent_rate_limits_background(
        self,
        client,
        hashes,
        download_limit,
        upload_limit,
        generation,
    ):
        failed = 0
        last_error = None
        for torrent_hash in hashes:
            if generation != self.client_generation or self._closing:
                return
            try:
                client.set_torrent_rate_limits(
                    torrent_hash,
                    download_limit,
                    upload_limit,
                )
            except Exception as exc:  # noqa: BLE001 - remote client boundary
                failed += 1
                last_error = exc

        if generation != self.client_generation or self._closing:
            return
        if failed == 0:
            wx.CallAfter(
                self._on_action_complete,
                self._("Selected torrent speed limits updated."),
            )
        elif failed < len(hashes):
            wx.CallAfter(
                self.statusbar.SetStatusText,
                self._(
                    "Speed limit update completed with {failed} failure(s). Last error: {error}"
                ).format(failed=failed, error=last_error),
                0,
            )
            wx.CallAfter(self.refresh_data)
        else:
            wx.CallAfter(
                self._on_action_error,
                self._("Failed to update torrent speed limits: {error}").format(
                    error=last_error
                ),
            )

    def _run_queue_action(self, method_name, progress_message, success_message):
        if not self.client:
            self.statusbar.SetStatusText(self._("Not connected to any client."), 0)
            return
        if not getattr(self.client, "supports_queue_reordering", False):
            self.statusbar.SetStatusText(
                self._("Queue reordering is not supported by this client."),
                0,
            )
            return

        hashes = self.torrent_list.get_selected_hashes()
        if not hashes:
            self.statusbar.SetStatusText(self._("No torrents selected."), 0)
            return

        action = getattr(self.client, method_name)
        generation = self.client_generation
        self.statusbar.SetStatusText(progress_message, 0)
        self.thread_pool.submit(
            self._queue_action_background,
            action,
            hashes,
            generation,
            success_message,
            self._("Queue action completed with {failed} failure(s). Last error: {error}"),
            self._("Queue action failed: {error}"),
        )

    def _queue_action_background(
        self,
        action,
        hashes,
        generation,
        success_message,
        partial_template,
        failure_template,
    ):
        failed = 0
        last_error = None
        for torrent_hash in hashes:
            if generation != self.client_generation or self._closing:
                return
            try:
                action(torrent_hash)
            except Exception as exc:  # noqa: BLE001 - remote client boundary
                failed += 1
                last_error = exc

        if generation != self.client_generation or self._closing:
            return
        if failed == 0:
            wx.CallAfter(self._on_action_complete, success_message)
        elif failed < len(hashes):
            wx.CallAfter(
                self.statusbar.SetStatusText,
                partial_template.format(failed=failed, error=last_error),
                0,
            )
            wx.CallAfter(self.refresh_data)
        else:
            wx.CallAfter(
                self._on_action_error,
                failure_template.format(error=last_error),
            )

    def on_queue_top(self, event):
        self._run_queue_action(
            "queue_top",
            self._("Moving selected torrents to the top of the queue..."),
            self._("Selected torrents moved to the top of the queue."),
        )

    def on_queue_up(self, event):
        self._run_queue_action(
            "queue_up",
            self._("Moving selected torrents up in the queue..."),
            self._("Selected torrents moved up in the queue."),
        )

    def on_queue_down(self, event):
        self._run_queue_action(
            "queue_down",
            self._("Moving selected torrents down in the queue..."),
            self._("Selected torrents moved down in the queue."),
        )

    def on_queue_bottom(self, event):
        self._run_queue_action(
            "queue_bottom",
            self._("Moving selected torrents to the bottom of the queue..."),
            self._("Selected torrents moved to the bottom of the queue."),
        )

    def _diagnostic_text(self, finding):
        code = finding.get("code")
        if code == "complete":
            return self._("Download is complete.")
        if code == "checking":
            return self._("Torrent is being checked.")
        if code == "paused":
            return self._("Torrent is paused or stopped.")
        if code == "client_error":
            return self._("Client reports an error: {message}").format(
                message=finding.get("message", "")
            )
        if code == "receiving_data":
            return self._("Torrent is currently receiving data.")
        if code == "no_seeds":
            return self._("No seeds are currently reported.")
        if code == "seeds_not_connected":
            return self._("{count} seeds are reported, but none are connected.").format(
                count=finding.get("count", 0)
            )
        if code in {"no_complete_copy", "incomplete_copy"}:
            return self._("The connected swarm does not currently expose a complete copy.")
        if code == "active_no_data":
            return self._("Torrent is active but currently receiving no data.")
        return self._("No clear cause is visible from the current torrent data.")

    def on_try_fix_stalled_torrents(self, event):
        if not self.client:
            self.statusbar.SetStatusText(self._("Not connected to any client."), 0)
            return

        torrents, missing = self._get_selected_torrent_objects()
        if not torrents and not missing:
            self.statusbar.SetStatusText(self._("No torrents selected."), 0)
            return

        hashes = []
        skipped = len(missing)
        for torrent in torrents:
            torrent_hash = str(torrent.get("hash") or "").strip()
            if not torrent_hash:
                skipped += 1
                continue
            try:
                size = float(torrent.get("size") or 0)
                done = float(torrent.get("done") or 0)
            except (TypeError, ValueError):
                size = done = 0
            findings = diagnose_torrent(torrent)
            finding_codes = {finding.get("code") for finding in findings}
            if (
                (size > 0 and done >= size)
                or bool(torrent.get("hashing"))
                or finding_codes.intersection({"complete", "checking", "receiving_data"})
            ):
                skipped += 1
                continue
            hashes.append(torrent_hash)

        if not hashes:
            self.statusbar.SetStatusText(
                self._("No recoverable incomplete torrents selected."),
                0,
            )
            return

        generation = self.client_generation
        self.statusbar.SetStatusText(self._("Trying safe recovery actions..."), 0)
        self.thread_pool.submit(
            self._recover_stalled_torrents_background,
            self.client,
            generation,
            hashes,
            skipped,
        )

    def _recover_stalled_torrents_background(
        self,
        client,
        generation,
        hashes,
        skipped,
    ):
        failed = 0
        last_error = None
        for torrent_hash in hashes:
            if generation != self.client_generation or self._closing:
                return
            try:
                client.start_torrent(torrent_hash)
                client.reannounce_torrent(torrent_hash)
            except Exception as exc:  # noqa: BLE001 - remote client boundary
                failed += 1
                last_error = exc

        if generation != self.client_generation or self._closing:
            return

        succeeded = len(hashes) - failed
        if failed == 0:
            message = self._("Recovery actions sent to {count} torrent(s).").format(
                count=succeeded
            )
            if skipped:
                message += " " + self._(
                    "{count} torrent(s) skipped because they are complete, checking, downloading, or unavailable."
                ).format(count=skipped)
            wx.CallAfter(self._on_action_complete, message)
            return

        if succeeded:
            message = self._(
                "Recovery actions sent to {succeeded} torrent(s); {failed} failed. Last error: {error}"
            ).format(
                succeeded=succeeded,
                failed=failed,
                error=last_error,
            )
            if skipped:
                message += " " + self._(
                    "{count} torrent(s) skipped because they are complete, checking, downloading, or unavailable."
                ).format(count=skipped)
            wx.CallAfter(self.statusbar.SetStatusText, message, 0)
            wx.CallAfter(self._record_activity, message, "error")
            wx.CallAfter(self.refresh_data)
            return

        wx.CallAfter(
            self._on_action_error,
            self._("Failed to send recovery actions: {error}").format(
                error=last_error
            ),
        )

    def on_diagnose_torrent(self, event):
        torrents, _missing = self._get_selected_torrent_objects()
        if len(torrents) != 1:
            wx.MessageBox(
                self._("Select one torrent to diagnose."),
                self._("Torrent Diagnosis"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        torrent = torrents[0]
        findings = diagnose_torrent(torrent)
        lines = [self._diagnostic_text(finding) for finding in findings]
        message = self._("Torrent: {name}").format(
            name=torrent.get("name") or torrent.get("hash") or self._("Unknown")
        )
        message += "\n\n" + "\n".join(f"- {line}" for line in lines)
        wx.MessageBox(
            message,
            self._("Torrent Diagnosis"),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def on_about(self, event):
        from app_version import APP_VERSION

        info = wx.adv.AboutDialogInfo()
        info.SetName("SerrebiTorrent")
        info.SetVersion(APP_VERSION)
        info.SetDescription(
            self._(
                "A Windows desktop torrent manager designed for keyboard-first use and screen readers."
            )
        )
        info.SetCopyright("Copyright © 2025-2026 serrebidev and contributors")
        info.SetWebSite("https://github.com/serrebidev/SerrebiTorrent")
        info.AddDeveloper("serrebidev")
        wx.adv.AboutBox(info)

    def _check_disk_space_before_add(self, client, data, save_path, priorities):
        preferences = self.config_manager.get_preferences()
        reserve_mib = max(0, int(preferences.get("disk_space_reserve_mib", 0) or 0))
        if reserve_mib <= 0:
            return

        if not getattr(client, "supports_free_space_query", False):
            raise RuntimeError(
                self._(
                    "Disk-space protection is enabled, but this client cannot report free space."
                )
            )

        target_path = save_path or client.get_default_save_path()
        if not target_path:
            raise RuntimeError(
                self._(
                    "Disk-space protection is enabled, but the destination path is unavailable."
                )
            )

        required_bytes = torrent_required_bytes(data, priorities)
        if required_bytes is None:
            raise RuntimeError(
                self._("Disk-space protection could not determine the torrent size.")
            )

        free_bytes = int(client.get_free_space(target_path))
        reserve_bytes = reserve_mib * 1024 * 1024
        if free_bytes - required_bytes < reserve_bytes:
            raise RuntimeError(
                self._(
                    "Not enough free disk space: {required} MiB required, {free} MiB free, "
                    "{reserve} MiB reserved."
                ).format(
                    required=f"{required_bytes / (1024 * 1024):.1f}",
                    free=f"{free_bytes / (1024 * 1024):.1f}",
                    reserve=reserve_mib,
                )
            )

    def _add_torrent_file_background(
        self,
        client,
        generation,
        data,
        save_path,
        priorities,
        status_msg,
    ):
        try:
            if generation != self.client_generation or self._closing:
                return
            if not client:
                raise RuntimeError(self._("Not connected to any client."))
            self._check_disk_space_before_add(
                client,
                data,
                save_path,
                priorities,
            )
        except Exception as exc:  # noqa: BLE001 - client/storage boundary
            if generation == self.client_generation and not self._closing:
                wx.CallAfter(
                    self._on_action_error,
                    self._("Torrent was not added: {error}").format(error=exc),
                )
            return

        super()._add_torrent_file_background(
            client,
            generation,
            data,
            save_path,
            priorities,
            status_msg,
        )

    def _restore_statusbar_accessible_name(self, announced_name, original_name):
        if self._closing or not hasattr(self, "statusbar"):
            return
        if self.statusbar.GetName() == announced_name:
            self.statusbar.SetName(original_name)

    def _completion_message(self, completed):
        if len(completed) == 1:
            return self._("Download complete: {name}").format(name=completed[0])
        return self._("{count} downloads completed.").format(count=len(completed))

    def _announce_download_completion(self, completed):
        if not hasattr(self, "statusbar"):
            return
        message = self._completion_message(completed)

        self.statusbar.SetStatusText(message, 0)
        original_name = self.statusbar.GetName()
        self.statusbar.SetName(message)
        legacy.notify_win_event(
            0x800C,  # EVENT_OBJECT_NAMECHANGE
            self.statusbar.GetHandle(),
            legacy.OBJID_CLIENT,
            0,
        )
        wx.CallLater(
            1500,
            self._restore_statusbar_accessible_name,
            message,
            original_name,
        )

    def _show_download_completion_notification(self, completed):
        message = self._completion_message(completed)
        try:
            notification = wx.adv.NotificationMessage(
                "SerrebiTorrent",
                message,
                parent=self,
            )
            self._download_complete_notification = notification
            notification.Show(timeout=wx.adv.NotificationMessage.Timeout_Auto)
        except Exception:
            # Notifications are optional OS integration. Failure must never
            # disrupt completion tracking or screen-reader feedback.
            self._download_complete_notification = None

    def _move_completed_background(
        self,
        client,
        generation,
        completed_events,
        destination,
        pause_after,
    ):
        if generation != self.client_generation or self._closing:
            return

        move_supported = getattr(client, "supports_move_storage", False)
        moved = 0
        move_failures = []
        pause_failures = []

        for event in completed_events:
            if generation != self.client_generation or self._closing:
                return

            if move_supported:
                try:
                    client.move_torrent_data(event["hash"], destination)
                    moved += 1
                except Exception as exc:  # noqa: BLE001 - client boundary
                    move_failures.append((event["name"], exc))

            if pause_after:
                try:
                    client.stop_torrent(event["hash"])
                except Exception as exc:  # noqa: BLE001 - client boundary
                    pause_failures.append((event["name"], exc))

        if generation != self.client_generation or self._closing:
            return

        if not move_supported:
            message = self._(
                "Automatic move on completion is not supported by this client."
            )
            wx.CallAfter(self.statusbar.SetStatusText, message, 0)
            wx.CallAfter(self._record_activity, message, "error")
        elif moved:
            message = self._(
                "Moved {count} completed torrent(s) to {destination}."
            ).format(
                count=moved,
                destination=destination,
            )
            wx.CallAfter(self.statusbar.SetStatusText, message, 0)
            wx.CallAfter(self._record_activity, message, "success")

        if move_failures:
            name, error = move_failures[0]
            message = self._(
                "Failed to move completed torrent {name}: {error}"
            ).format(name=name, error=error)
            wx.CallAfter(self.statusbar.SetStatusText, message, 0)
            wx.CallAfter(self._record_activity, message, "error")

        if pause_failures:
            name, error = pause_failures[0]
            message = self._(
                "Failed to pause completed torrent {name}: {error}"
            ).format(name=name, error=error)
            wx.CallAfter(self.statusbar.SetStatusText, message, 0)
            wx.CallAfter(self._record_activity, message, "error")

        wx.CallAfter(self.refresh_data)

    def _pause_completed_background(self, client, generation, completed_events):
        if generation != self.client_generation or self._closing:
            return

        failures = []
        for event in completed_events:
            if generation != self.client_generation or self._closing:
                return
            try:
                client.stop_torrent(event["hash"])
            except Exception as exc:  # noqa: BLE001 - client boundary
                failures.append((event["name"], exc))

        if generation != self.client_generation or self._closing:
            return

        if failures:
            name, error = failures[0]
            wx.CallAfter(
                self.statusbar.SetStatusText,
                self._("Failed to pause completed torrent {name}: {error}").format(
                    name=name,
                    error=error,
                ),
                0,
            )
        wx.CallAfter(self.refresh_data)

    def _schedule_disk_space_guard(
        self,
        client,
        generation,
        torrents,
        reserve_mib,
    ):
        if (
            self._disk_space_guard_busy
            or reserve_mib <= 0
            or not client
            or not getattr(client, "supports_free_space_query", False)
        ):
            return

        groups = active_download_groups(torrents)
        if not groups:
            return

        self._disk_space_guard_busy = True
        try:
            self.thread_pool.submit(
                self._disk_space_guard_background,
                client,
                generation,
                groups,
                reserve_mib,
            )
        except RuntimeError:
            self._disk_space_guard_busy = False

    def _disk_space_guard_background(
        self,
        client,
        generation,
        groups,
        reserve_mib,
    ):
        paused = []
        failures = []
        reserve_bytes = int(reserve_mib) * 1024 * 1024

        try:
            for save_path, events in groups.items():
                if generation != self.client_generation or self._closing:
                    return
                try:
                    free_bytes = int(client.get_free_space(save_path))
                except NotImplementedError:
                    continue
                except Exception:
                    # A transient free-space query failure must not disrupt
                    # normal refreshes or spam the user every two seconds.
                    continue

                if free_bytes > reserve_bytes:
                    continue

                for event in events:
                    if generation != self.client_generation or self._closing:
                        return
                    try:
                        client.stop_torrent(event["hash"])
                        paused.append(event)
                    except Exception as exc:  # noqa: BLE001 - client boundary
                        failures.append((event["name"], exc))
        finally:
            wx.CallAfter(
                self._on_disk_space_guard_done,
                generation,
                paused,
                failures,
            )

    def _on_disk_space_guard_done(self, generation, paused, failures):
        self._disk_space_guard_busy = False
        if (
            self._closing
            or generation != self.client_generation
            or not self.connected
        ):
            return
        if not paused and not failures:
            return

        if failures:
            message = self._(
                "Disk-space reserve reached; paused {paused} download(s), "
                "{failed} pause(s) failed. Last error: {error}"
            ).format(
                paused=len(paused),
                failed=len(failures),
                error=failures[-1][1],
            )
            kind = "error"
        else:
            message = self._(
                "Disk-space reserve reached; paused {count} active download(s)."
            ).format(count=len(paused))
            kind = "success"

        self.statusbar.SetStatusText(message, 0)
        original_name = self.statusbar.GetName()
        self.statusbar.SetName(message)
        legacy.notify_win_event(
            0x800C,
            self.statusbar.GetHandle(),
            legacy.OBJID_CLIENT,
            0,
        )
        wx.CallLater(
            1500,
            self._restore_statusbar_accessible_name,
            message,
            original_name,
        )
        self._record_activity(message, kind=kind)

    def _ratio_target_events(self, torrents, target):
        events = []
        threshold = float(target) * 1000.0
        for torrent in torrents:
            torrent_hash = str(torrent.get("hash") or "").strip()
            if not torrent_hash or torrent_hash in self._ratio_pause_pending:
                continue
            try:
                size = float(torrent.get("size") or 0)
                done = float(torrent.get("done") or 0)
                ratio = float(torrent.get("ratio") or 0)
                state = int(torrent.get("state") or 0)
            except (TypeError, ValueError):
                continue
            if size <= 0 or done < size or state != 1 or ratio < threshold:
                continue
            events.append(
                {
                    "hash": torrent_hash,
                    "name": str(torrent.get("name") or torrent_hash),
                    "ratio": ratio / 1000.0,
                }
            )
        return events

    def _pause_seed_ratio_background(self, client, generation, events, target):
        failures = []
        for event in events:
            torrent_hash = event["hash"]
            if generation != self.client_generation or self._closing:
                self._ratio_pause_pending.discard(torrent_hash)
                continue
            try:
                client.stop_torrent(torrent_hash)
                message = self._(
                    "Paused {name} at ratio {ratio:.2f} (target {target:.2f})."
                ).format(
                    name=event["name"],
                    ratio=event["ratio"],
                    target=target,
                )
                wx.CallAfter(self._record_activity, message, "success")
            except Exception as exc:  # noqa: BLE001 - client boundary
                failures.append((event["name"], exc))
            finally:
                self._ratio_pause_pending.discard(torrent_hash)

        if generation != self.client_generation or self._closing:
            return
        if failures:
            name, error = failures[0]
            message = self._(
                "Failed to pause {name} at the seed ratio target: {error}"
            ).format(name=name, error=error)
            wx.CallAfter(self.statusbar.SetStatusText, message, 0)
            wx.CallAfter(self._record_activity, message, "error")
        elif events:
            wx.CallAfter(
                self.statusbar.SetStatusText,
                self._("Seed ratio target reached; matching torrents were paused."),
                0,
            )
        wx.CallAfter(self.refresh_data)

    def _on_refresh_complete(
        self,
        generation,
        torrents,
        display_data,
        stats,
        tracker_counts,
        g_down,
        g_up,
    ):
        filtered_display_data = display_data
        if self.current_filter.startswith("category:"):
            wanted_category = self.current_filter.split(":", 1)[1]
            filtered_display_data = [
                torrent
                for torrent in torrents
                if self.torrent_categories.get(
                    self.current_profile_id,
                    torrent.get("hash"),
                ) == wanted_category
            ]
        query = self._name_filter_query.strip().casefold()
        if query:
            filtered_display_data = [
                torrent
                for torrent in filtered_display_data
                if query in str(torrent.get("name") or "").casefold()
            ]

        super()._on_refresh_complete(
            generation,
            torrents,
            filtered_display_data,
            stats,
            tracker_counts,
            g_down,
            g_up,
        )
        if (
            self._closing
            or generation != self.client_generation
            or not self.connected
        ):
            return

        completion_events = self._completion_tracker.update_events(torrents)
        completed = [event["name"] for event in completion_events]
        for event in completion_events:
            self._record_activity(
                self._("Download complete: {name}").format(name=event["name"]),
                kind="success",
            )
        preferences = self.config_manager.get_preferences()
        try:
            disk_reserve_mib = max(
                0,
                int(preferences.get("disk_space_reserve_mib", 0) or 0),
            )
        except (TypeError, ValueError):
            disk_reserve_mib = 0
        self._schedule_disk_space_guard(
            self.client,
            generation,
            torrents,
            disk_reserve_mib,
        )
        if completed and preferences.get("announce_download_complete", True):
            self._announce_download_completion(completed)
        if completed and preferences.get("show_download_complete_notification", False):
            self._show_download_completion_notification(completed)

        try:
            seed_ratio_target = float(
                preferences.get("pause_at_seed_ratio", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            seed_ratio_target = 0.0
        if seed_ratio_target > 0:
            ratio_events = self._ratio_target_events(torrents, seed_ratio_target)
            if ratio_events:
                for event in ratio_events:
                    self._ratio_pause_pending.add(event["hash"])
                try:
                    self.thread_pool.submit(
                        self._pause_seed_ratio_background,
                        self.client,
                        generation,
                        ratio_events,
                        seed_ratio_target,
                    )
                except RuntimeError:
                    for event in ratio_events:
                        self._ratio_pause_pending.discard(event["hash"])

        move_destination = str(
            preferences.get("move_completed_to_path", "") or ""
        ).strip()
        pause_after = preferences.get("pause_on_download_complete", False)
        if completion_events and move_destination:
            try:
                self.thread_pool.submit(
                    self._move_completed_background,
                    self.client,
                    generation,
                    completion_events,
                    move_destination,
                    pause_after,
                )
            except RuntimeError:
                pass
        elif completion_events and pause_after:
            try:
                self.thread_pool.submit(
                    self._pause_completed_background,
                    self.client,
                    generation,
                    completion_events,
                )
            except RuntimeError:
                pass

        self._refresh_category_sidebar(torrents)
        language = self._language()
        for key, item_id in self.cat_ids.items():
            self.sidebar.SetItemText(item_id, sidebar_label(key, stats.get(key, 0), language))
        self.sidebar.SetItemText(self.trackers_root, tr_main("Trackers", language))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        raise SystemExit(legacy.frozen_self_test(sys.argv[2]))

    try:
        print("Starting application...")
        app = wx.App(False)
        print("wx.App initialized.")

        name = f"SerrebiTorrent-{wx.GetUserId()}"
        checker = wx.SingleInstanceChecker(name)
        if checker.IsAnotherRunning():
            wx.MessageBox(
                tr_main("Another instance of SerrebiTorrent is already running.", "system"),
                tr_main("Error", "system"),
                wx.OK | wx.ICON_ERROR,
            )
            return 0

        legacy.updater.cleanup_update_artifacts()
        frame = LocalizedMainFrame()
        print("MainFrame initialized.")
        frame.Show()
        print("MainFrame shown. Entering MainLoop.")
        app.MainLoop()
        print("MainLoop exited.")
        return 0
    except Exception as exc:  # noqa: BLE001 - application boundary
        print(f"CRITICAL ERROR: {exc}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
