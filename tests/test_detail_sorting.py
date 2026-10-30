"""Sorting tests for the Files / Peers / Trackers detail lists (issue #420).

The torrent list already sorted on column-header click; the detail lists
did not. These tests exercise ``DetailColumnSortMixin`` and each list's
``set_data`` with stubs (no display / wx.App required), mirroring
``test_list_accessibility.py``.
"""

import inspect

import main


class FakeEvent:
    def __init__(self, col):
        self._col = col

    def GetColumn(self):
        return self._col


class FakeDetailList(main.DetailColumnSortMixin, main.AccessibleVirtualListMixin):
    """Stubs the wx.ListCtrl surface the sort mixin relies on."""

    def __init__(self, data, focused=-1, selected=()):
        self.data = list(data)
        self._focused = focused
        self._selected = set(selected)
        self.sort_col = -1
        self.sort_asc = True
        self.refresh_calls = 0
        self.restored = []

    def GetFocusedItem(self):
        return self._focused

    def GetFirstSelected(self):
        return min(self._selected) if self._selected else -1

    def GetNextSelected(self, item):
        later = [i for i in self._selected if i > item]
        return min(later) if later else -1

    def Select(self, idx, on=True):
        if on:
            self._selected.add(idx)
        else:
            self._selected.discard(idx)

    def Refresh(self):
        self.refresh_calls += 1

    def _restore_focus_row(self, item_count, preserve_idx=None, force=False):
        self.restored.append((item_count, preserve_idx))
        if preserve_idx is not None:
            self._focused = preserve_idx


class FakePeersList(FakeDetailList):
    SORT_KEYS = main.PeersListCtrl.SORT_KEYS
    _row_identity = main.PeersListCtrl._row_identity
    set_data = main.PeersListCtrl.set_data

    def GetItemCount(self):
        return len(self.data)

    def SetItemCount(self, n):
        # wx drops the focused row on SetItemCount; the mixin restores it.
        self._focused = -1

    def SetItemState(self, idx, state, mask):
        self._focused = idx

    def EnsureVisible(self, idx):
        pass

    def _list_has_focus(self):
        return True


class FakeTrackersList(FakeDetailList):
    SORT_KEYS = main.TrackersListCtrl.SORT_KEYS
    _row_identity = main.TrackersListCtrl._row_identity


PEERS = [
    {"address": "10.0.0.2", "client": "qBittorrent", "progress": 0.5, "down_rate": 100, "up_rate": 5},
    {"address": "10.0.0.10", "client": "Transmission", "progress": 1.0, "down_rate": 900, "up_rate": 50},
    {"address": "10.0.0.1", "client": "Deluge", "progress": 0.25, "down_rate": 300, "up_rate": 500},
]


def test_click_sorts_by_column_and_second_click_reverses():
    lst = FakePeersList(PEERS)

    lst.on_col_click(FakeEvent(3))  # Down Speed
    assert [p["down_rate"] for p in lst.data] == [100, 300, 900]

    lst.on_col_click(FakeEvent(3))
    assert [p["down_rate"] for p in lst.data] == [900, 300, 100]


def test_string_columns_sort_case_insensitively():
    lst = FakePeersList(PEERS)

    lst.on_col_click(FakeEvent(1))  # Client
    assert [p["client"] for p in lst.data] == ["Deluge", "qBittorrent", "Transmission"]


def test_numeric_columns_sort_numerically_not_lexicographically():
    trackers = [
        {"url": "udp://a", "status": "Working", "peers": 9, "message": ""},
        {"url": "udp://b", "status": "Working", "peers": 100, "message": ""},
        {"url": "udp://c", "status": "Working", "peers": 10, "message": ""},
    ]
    lst = FakeTrackersList(trackers)

    lst.on_col_click(FakeEvent(2))  # Peers
    assert [t["peers"] for t in lst.data] == [9, 10, 100]


def test_sort_preserves_focus_and_selection_by_identity():
    lst = FakePeersList(PEERS, focused=0, selected={0, 2})

    lst.on_col_click(FakeEvent(3))  # Down Speed: 100, 300, 900
    # Focused row was 10.0.0.2 (down 100) -> still focused, now at index 0.
    assert lst.restored == [(3, 0)]
    # Selected rows were down 100 and down 300 -> indices 0 and 1 after sort.
    assert lst._selected == {0, 1}


def test_peers_set_data_reapplies_sort_and_restores_focus():
    lst = FakePeersList(PEERS, focused=1)
    lst.sort_col = 3  # Down Speed
    lst.sort_asc = True

    refreshed = [dict(p) for p in reversed(PEERS)]
    lst.set_data(refreshed)

    assert [p["down_rate"] for p in lst.data] == [100, 300, 900]
    # Focused peer was 10.0.0.10 (down 900) -> index 2 after sorting.
    assert lst._focused == 2


def test_each_detail_list_binds_column_click_sorting():
    for cls in (main.FilesListCtrl, main.PeersListCtrl, main.TrackersListCtrl):
        assert issubclass(cls, main.DetailColumnSortMixin)
        assert "self.init_column_sort()" in inspect.getsource(cls.__init__)
        assert "self._apply_sort()" in inspect.getsource(cls.set_data)
        assert cls.SORT_KEYS


def test_detail_sort_keys_match_displayed_columns():
    assert main.FilesListCtrl.SORT_KEYS == ("name", "size", "progress", "priority")
    assert main.PeersListCtrl.SORT_KEYS == (
        "address",
        "client",
        "progress",
        "down_rate",
        "up_rate",
    )
    assert main.TrackersListCtrl.SORT_KEYS == ("url", "status", "peers", "message")
