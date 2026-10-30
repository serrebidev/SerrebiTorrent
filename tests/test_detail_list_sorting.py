"""Header-click sorting for the Files / Peers / Trackers detail lists.

Issue #420: emwgee asked to sort the detail tabs by clicking a column
header, the way the torrent list already works. These tests exercise the
classes' sort logic with stubs (no display / wx.App required), following
the pattern in test_list_accessibility.py.
"""

import main


class FakeEvent:
    def __init__(self, col):
        self._col = col

    def GetColumn(self):
        return self._col


class FakeDetailList:
    _apply_sort = main.ColumnSortMixin._apply_sort
    on_col_click = main.ColumnSortMixin.on_col_click

    def __init__(self, rows):
        self.data = list(rows)
        self.sort_col = -1
        self.sort_asc = True
        self.count_calls = []

    def GetFocusedItem(self):
        return -1

    def set_virtual_item_count(self, count, focus_index=None):
        self.count_calls.append((count, focus_index))


class FakeFilesList(FakeDetailList):
    sort_key_funcs = main.FilesListCtrl.sort_key_funcs
    _focused_file_key = main.FilesListCtrl._focused_file_key
    _index_of_file_key = main.FilesListCtrl._index_of_file_key
    set_data = main.FilesListCtrl.set_data


class FakePeersList(FakeDetailList):
    sort_key_funcs = main.PeersListCtrl.sort_key_funcs
    set_data = main.PeersListCtrl.set_data


class FakeTrackersList(FakeDetailList):
    sort_key_funcs = main.TrackersListCtrl.sort_key_funcs
    set_data = main.TrackersListCtrl.set_data


def file_row(name, size, progress=0.0, priority=1, index=0):
    return {
        "index": index,
        "name": name,
        "size": size,
        "progress": progress,
        "priority": priority,
    }


def test_files_unsorted_until_header_clicked():
    rows = [file_row("b.mkv", 2), file_row("a.mkv", 1)]
    lst = FakeFilesList(rows)
    lst.set_data(rows)
    assert [r["name"] for r in lst.data] == ["b.mkv", "a.mkv"]


def test_files_click_size_sorts_then_reverses():
    lst = FakeFilesList(
        [file_row("big", 300), file_row("small", 100), file_row("mid", 200)]
    )
    lst.on_col_click(FakeEvent(1))
    assert [r["size"] for r in lst.data] == [100, 200, 300]
    lst.on_col_click(FakeEvent(1))
    assert [r["size"] for r in lst.data] == [300, 200, 100]


def test_files_name_sort_uses_displayed_basename_case_insensitive():
    lst = FakeFilesList(
        [
            file_row("dir/Zebra.mkv", 1),
            file_row("dir/apple.mkv", 1),
            file_row("other/Banana.mkv", 1),
        ]
    )
    lst.on_col_click(FakeEvent(0))
    assert [r["name"] for r in lst.data] == [
        "dir/apple.mkv",
        "other/Banana.mkv",
        "dir/Zebra.mkv",
    ]


def test_files_sort_survives_refresh():
    lst = FakeFilesList([file_row("b", 2), file_row("a", 1)])
    lst.on_col_click(FakeEvent(1))
    lst.set_data([file_row("d", 4), file_row("c", 3)])
    assert [r["name"] for r in lst.data] == ["c", "d"]


def test_peers_down_speed_sorts_numerically():
    rows = [
        {"address": "1.1.1.1", "client": "A", "progress": 0.5, "down_rate": 10000, "up_rate": 0},
        {"address": "2.2.2.2", "client": "B", "progress": 0.5, "down_rate": 900, "up_rate": 0},
        {"address": "3.3.3.3", "client": "C", "progress": 0.5, "down_rate": 50000, "up_rate": 0},
    ]
    lst = FakePeersList(rows)
    lst.on_col_click(FakeEvent(3))
    assert [r["down_rate"] for r in lst.data] == [900, 10000, 50000]


def test_trackers_peer_count_sorts_numerically():
    rows = [
        {"url": "udp://b.example", "status": "Working", "peers": 9, "message": ""},
        {"url": "udp://a.example", "status": "Working", "peers": 120, "message": ""},
        {"url": "udp://c.example", "status": "Working", "peers": 30, "message": ""},
    ]
    lst = FakeTrackersList(rows)
    lst.on_col_click(FakeEvent(2))
    assert [r["peers"] for r in lst.data] == [9, 30, 120]
    lst.on_col_click(FakeEvent(0))
    assert [r["url"] for r in lst.data] == [
        "udp://a.example",
        "udp://b.example",
        "udp://c.example",
    ]
