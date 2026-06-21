"""Accessibility regression tests for the virtual-list focus handling.

NVDA announces the row carrying ``wx.LIST_STATE_FOCUSED`` as the user arrows
through a ``wx.LC_VIRTUAL`` list. ``AccessibleVirtualListMixin`` re-asserts that
focused row after every populate so arrow navigation keeps speaking. These tests
exercise the decision logic with a stub (no display / wx.App required) so the
behaviour is verified in CI.
"""

import wx

import main


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

    def _list_has_focus(self):
        return self._has_focus


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
