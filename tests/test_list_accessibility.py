"""Accessibility regression tests for the virtual-list focus handling.

NVDA announces the row carrying ``wx.LIST_STATE_FOCUSED`` as the user arrows
through a ``wx.LC_VIRTUAL`` list. ``AccessibleVirtualListMixin`` re-asserts that
focused row after every populate so arrow navigation keeps speaking. These tests
exercise the decision logic with a stub (no display / wx.App required) so the
behaviour is verified in CI.
"""

import wx

import main


class FakeTorrentListForDetails:
    def __init__(self, focused_hash=None, selected_hashes=None):
        self.focused_hash = focused_hash
        self.selected_hashes = selected_hashes or []

    def get_focused_hash(self):
        return self.focused_hash

    def get_selected_hashes(self):
        return list(self.selected_hashes)


class FakeVirtualList(main.AccessibleVirtualListMixin):
    """Stubs the wx.ListCtrl surface the mixin relies on, recording calls."""

    def __init__(self, focused=-1, item_count=0, has_focus=False):
        self._focused = focused
        self._item_count = item_count
        self._has_focus = has_focus
        self.set_state_calls = []
        self.ensure_visible_calls = []
        self.set_count_calls = []
        self.refresh_calls = 0
        self.focus_event_calls = []

    def GetFocusedItem(self):
        return self._focused

    def GetItemCount(self):
        return self._item_count

    def SetItemCount(self, n):
        self._item_count = n
        self.set_count_calls.append(n)

    def Refresh(self):
        self.refresh_calls += 1

    def SetItemState(self, idx, state, mask):
        # The native control moves the focused item to idx.
        self._focused = idx
        self.set_state_calls.append((idx, state, mask))

    def EnsureVisible(self, idx):
        self.ensure_visible_calls.append(idx)

    def GetHandle(self):
        return 1234

    def _list_has_focus(self):
        return self._has_focus

    def _notify_accessible_focus_event(self, idx):
        self.focus_event_calls.append(idx)
        return True


class FakeFilesList(FakeVirtualList):
    _focused_file_key = main.FilesListCtrl._focused_file_key
    _index_of_file_key = main.FilesListCtrl._index_of_file_key
    set_data = main.FilesListCtrl.set_data

    def __init__(self, data, focused=-1, item_count=0, has_focus=False):
        super().__init__(focused=focused, item_count=item_count, has_focus=has_focus)
        self.data = data

    def SetItemCount(self, n):
        super().SetItemCount(n)
        self._focused = -1


def test_focus_moves_to_preserved_row_when_list_has_focus():
    lst = FakeVirtualList(focused=2, item_count=10, has_focus=True)
    lst._restore_focus_row(10, preserve_idx=5)
    # Moving focus to row 5 is what fires the native event NVDA announces.
    assert lst.set_state_calls == [(5, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)]
    assert lst.ensure_visible_calls == [5]


def test_focus_noop_when_already_on_target_row():
    lst = FakeVirtualList(focused=5, item_count=10, has_focus=True)
    lst._restore_focus_row(10, preserve_idx=5)
    # Already focused there -> must not re-fire (would double-speak every 2s).
    assert lst.set_state_calls == []


def test_focus_can_be_forced_when_screen_reader_needs_transition():
    lst = FakeVirtualList(focused=5, item_count=10, has_focus=True)
    lst._restore_focus_row(10, preserve_idx=5, force=True)
    assert lst.set_state_calls == [
        (5, 0, wx.LIST_STATE_FOCUSED),
        (5, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED),
    ]
    assert lst.ensure_visible_calls == [5]


def test_focus_not_stolen_when_unfocused_and_row_exists():
    lst = FakeVirtualList(focused=3, item_count=10, has_focus=False)
    lst._restore_focus_row(10, preserve_idx=7)
    # Background refresh while the user works elsewhere must not move focus.
    assert lst.set_state_calls == []


def test_focus_seeds_baseline_when_unfocused_and_none_exists():
    lst = FakeVirtualList(focused=-1, item_count=10, has_focus=False)
    lst._restore_focus_row(10, preserve_idx=4)
    # Seed a focused row (no announcement, no scroll) so the first Tab+arrow works.
    assert lst.set_state_calls == [(4, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)]
    assert lst.ensure_visible_calls == []


def test_focus_clamped_to_last_row():
    lst = FakeVirtualList(focused=0, item_count=3, has_focus=True)
    lst._restore_focus_row(3, preserve_idx=99)
    assert lst.set_state_calls == [(2, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)]


def test_focus_noop_on_empty_list():
    lst = FakeVirtualList(focused=-1, item_count=0, has_focus=True)
    lst._restore_focus_row(0, preserve_idx=0)
    assert lst.set_state_calls == []


def test_set_virtual_item_count_skips_setcount_when_unchanged():
    lst = FakeVirtualList(focused=2, item_count=5, has_focus=True)
    lst.set_virtual_item_count(5, preserve_idx=2)
    # Unchanged count -> no SetItemCount churn (which would wipe focus)...
    assert lst.set_count_calls == []
    # ...but still repaint so updated row text shows.
    assert lst.refresh_calls == 1


def test_set_virtual_item_count_sets_count_when_changed():
    lst = FakeVirtualList(focused=-1, item_count=5, has_focus=False)
    lst.set_virtual_item_count(8)
    assert lst.set_count_calls == [8]
    assert lst.refresh_calls == 1


def test_navigation_pulse_reasserts_new_focused_row():
    lst = FakeVirtualList(focused=3, item_count=8, has_focus=True)
    lst._accessible_pulse_navigation = True
    lst._force_focus_after_navigation(before_idx=2)
    assert lst.set_state_calls == [
        (3, 0, wx.LIST_STATE_FOCUSED),
        (3, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED),
    ]
    assert lst.ensure_visible_calls == [3]
    assert lst.focus_event_calls == [3]


def test_accessible_focus_event_uses_listview_child_id(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main,
        "notify_win_event",
        lambda event, hwnd, object_id, child_id: calls.append((event, hwnd, object_id, child_id)) or True,
    )

    lst = FakeVirtualList(focused=3, item_count=8, has_focus=True)
    assert main.AccessibleVirtualListMixin._notify_accessible_focus_event(lst, 3) is True
    assert calls == [(main.EVENT_OBJECT_FOCUS, 1234, main.OBJID_CLIENT, 4)]


def test_accessible_focus_event_skips_unfocused_list(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main,
        "notify_win_event",
        lambda event, hwnd, object_id, child_id: calls.append((event, hwnd, object_id, child_id)) or True,
    )

    lst = FakeVirtualList(focused=3, item_count=8, has_focus=False)
    assert main.AccessibleVirtualListMixin._notify_accessible_focus_event(lst, 3) is False
    assert calls == []


def test_accessible_focus_event_deduplicates_same_row(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main,
        "notify_win_event",
        lambda event, hwnd, object_id, child_id: calls.append((event, hwnd, object_id, child_id)) or True,
    )

    lst = FakeVirtualList(focused=3, item_count=8, has_focus=True)
    assert main.AccessibleVirtualListMixin._notify_accessible_focus_event(lst, 3) is True
    assert main.AccessibleVirtualListMixin._notify_accessible_focus_event(lst, 3) is False
    assert calls == [(main.EVENT_OBJECT_FOCUS, 1234, main.OBJID_CLIENT, 4)]


def test_files_set_data_restores_focused_file_after_wx_count_reset():
    old_files = [
        {"index": 0, "name": "a.bin"},
        {"index": 1, "name": "b.bin"},
    ]
    new_files = [
        {"index": 0, "name": "a.bin"},
        {"index": 1, "name": "b.bin"},
        {"index": 2, "name": "c.bin"},
    ]
    lst = FakeFilesList(old_files, focused=1, item_count=2, has_focus=True)
    lst.set_data(new_files)
    assert lst.set_count_calls == [3]
    assert lst.set_state_calls == [(1, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)]
    assert lst.ensure_visible_calls == [1]


def test_detail_hash_uses_focused_torrent_before_selection():
    lst = FakeTorrentListForDetails(focused_hash="focused", selected_hashes=["selected"])
    assert main.active_torrent_hash_for_details(lst) == "focused"


def test_detail_hash_falls_back_to_selected_torrent():
    lst = FakeTorrentListForDetails(selected_hashes=["selected"])
    assert main.active_torrent_hash_for_details(lst) == "selected"


def test_detail_hash_empty_when_no_focus_or_selection():
    lst = FakeTorrentListForDetails()
    assert main.active_torrent_hash_for_details(lst) is None
