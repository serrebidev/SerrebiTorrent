from collections import deque
from unittest.mock import Mock

import pytest
import wx

import clients
import magnet_intake as intake

HASH = 'a' * 40
MAGNET = f'magnet:?xt=urn:btih:{HASH}&dn=Test&tr=https%3A%2F%2Fnew.example%2Fannounce'


class Frame(intake.MagnetIntakeMixin):
    def __init__(self):
        self._closing = False
        self.connected = True
        self.client_generation = 1
        self.client = Mock()
        self.client.find_magnet_duplicate.return_value = None
        self.client.handles_magnet_start = True
        self.config_manager = Mock()
        self.config_manager.get_preferences.return_value = {'clipboard_auto_add': True}
        self._clipboard_last_text = None
        self._magnet_queue = deque()
        self._magnet_busy = False
        self.pending_hash_starts = set()
        self.thread_pool = Mock()
        self.IsEnabled = Mock(return_value=True)
        self.IsIconized = Mock(return_value=False)
        self.Show = Mock()
        self.Raise = Mock()
        self._read_clipboard_text = Mock(return_value=MAGNET)
        self._get_default_save_path = Mock(return_value='/remote/downloads')
        self._on_action_error = Mock()
        self._on_action_complete = Mock()
        self._add_magnet_background = Mock()
        self._prepare_auto_start = Mock()


@pytest.fixture
def frame(monkeypatch):
    monkeypatch.setattr(wx, 'CallAfter', lambda fn, *args: fn(*args))
    return Frame()


def test_extract_magnets_validates_hashes_and_deduplicates():
    assert intake.clipboard_magnets(f'<{MAGNET}>\n{MAGNET}\nmagnet:?xt=bad') == [MAGNET]
    assert intake.clipboard_magnets('ordinary clipboard text') == []
    assert intake.clipboard_magnets('x' * (1024 * 1024 + 1) + MAGNET) == []
    assert intake.clipboard_magnets('magnet:?xt=urn:btmh:1220' + 'b' * 64)


def test_trackers_decode_once_and_deduplicate():
    assert intake.magnet_trackers(MAGNET + '&tr=https%3A%2F%2Fnew.example%2Fannounce') == ['https://new.example/announce']


@pytest.mark.parametrize('blocked', ['disabled', 'disconnected', 'closing', 'modal', 'busy'])
def test_clipboard_is_not_read_when_intake_blocked(frame, blocked):
    if blocked == 'disabled':
        frame.config_manager.get_preferences.return_value = {}
    elif blocked == 'disconnected':
        frame.connected = False
    elif blocked == 'closing':
        frame._closing = True
    elif blocked == 'modal':
        frame.IsEnabled.return_value = False
    else:
        frame._magnet_busy = True
    frame._on_clipboard_timer(None)
    frame._read_clipboard_text.assert_not_called()


def test_unchanged_clipboard_is_not_reprompted_after_cancel(frame):
    frame._queue_magnet = Mock()
    frame._on_clipboard_timer(None)
    frame._on_clipboard_timer(None)
    frame._queue_magnet.assert_called_once_with(MAGNET)
    frame._read_clipboard_text.return_value = 'another text'
    frame._on_clipboard_timer(None)
    frame._read_clipboard_text.return_value = MAGNET
    frame._on_clipboard_timer(None)
    assert frame._queue_magnet.call_count == 2


def test_clipboard_contention_is_retried(frame):
    frame._queue_magnet = Mock()
    frame._read_clipboard_text.side_effect = [None, MAGNET]
    frame._on_clipboard_timer(None)
    frame._on_clipboard_timer(None)
    frame._queue_magnet.assert_called_once_with(MAGNET)


def test_own_clipboard_copy_is_ignored(frame):
    frame._clipboard_last_text = MAGNET
    frame._queue_magnet = Mock()
    frame._on_clipboard_timer(None)
    frame._queue_magnet.assert_not_called()


def test_queue_drops_old_profile_entries_and_serializes(frame):
    frame._magnet_queue.extend([(frame.client, 0, MAGNET), (frame.client, 1, MAGNET), (frame.client, 1, MAGNET)])
    frame._drain_magnet_queue()
    frame._drain_magnet_queue()
    assert frame.thread_pool.submit.call_count == 1
    assert len(frame._magnet_queue) == 1


@pytest.mark.parametrize('answer', [wx.ID_OK, wx.ID_CANCEL])
def test_save_dialog_uses_remote_path_and_cancel_does_not_add(frame, monkeypatch, answer):
    dialog = Mock()
    dialog.ShowModal.return_value = answer
    dialog.get_selected_path.return_value = '/remote/chosen'
    factory = Mock(return_value=dialog)
    monkeypatch.setattr(intake, 'AddTorrentDialog', factory)
    frame._show_magnet(frame.client, 1, MAGNET, None, None)
    factory.assert_called_once_with(frame, 'Test', None, '/remote/downloads')
    dialog.Destroy.assert_called_once()
    if answer == wx.ID_OK:
        frame.thread_pool.submit.assert_called_once_with(frame._add_magnet_background, frame.client, 1, MAGNET, '/remote/chosen', 'Magnet link added')
    else:
        frame.thread_pool.submit.assert_not_called()
    frame._prepare_auto_start.assert_not_called()


def test_stale_or_failed_inspection_cannot_open_add_dialog(frame, monkeypatch):
    factory = Mock()
    monkeypatch.setattr(intake, 'AddTorrentDialog', factory)
    frame._show_magnet(frame.client, 0, MAGNET, None, None)
    frame._show_magnet(frame.client, 1, MAGNET, None, 'offline')
    factory.assert_not_called()
    frame._on_action_error.assert_called_once_with('offline')


@pytest.mark.parametrize('answer', [wx.YES, wx.NO])
def test_duplicate_prompts_only_for_new_trackers(frame, monkeypatch, answer):
    box = Mock(return_value=answer)
    monkeypatch.setattr(wx, 'MessageBox', box)
    frame._prompt_duplicate_magnet(frame.client, 1, MAGNET, (HASH, 'Existing', ['https://old.example/announce']))
    assert '1 new tracker' in box.call_args.args[0]
    if answer == wx.YES:
        frame.thread_pool.submit.assert_called_once_with(frame._merge_magnet_trackers, frame.client, 1, HASH, ['https://new.example/announce'])
    else:
        frame.thread_pool.submit.assert_not_called()
    frame.client.add_torrent_url.assert_not_called()


def test_duplicate_without_new_trackers_never_merges(frame, monkeypatch):
    monkeypatch.setattr(wx, 'MessageBox', Mock(return_value=wx.YES))
    frame._prompt_duplicate_magnet(frame.client, 1, MAGNET, (HASH, 'Existing', ['https://new.example/announce']))
    frame.thread_pool.submit.assert_not_called()


def test_profile_switch_prevents_tracker_merge(frame):
    frame._merge_magnet_trackers(frame.client, 0, HASH, ['https://new.example'])
    frame.client.add_trackers.assert_not_called()


@pytest.fixture
def transmission():
    client = object.__new__(clients.TransmissionClient)
    client.c = Mock()
    return client


def test_duplicate_reads_server_not_ui_cache(transmission):
    transmission.c.get_torrents.return_value = [{'hashString': HASH, 'name': 'Existing', 'trackers': [{'announce': 'https://old.example'}]}]
    assert transmission.find_magnet_duplicate(MAGNET) == (HASH, 'Existing', ['https://old.example'])
    transmission.c.get_torrents.assert_called_once_with(ids=[HASH], arguments=['hashString', 'name', 'trackers'])


def test_tracker_merge_only_adds_and_rechecks_existing(transmission):
    transmission.c.get_torrent.return_value = {'trackers': [{'announce': 'https://old.example'}]}
    transmission.add_trackers(HASH, ['https://old.example', 'https://new.example', 'https://new.example'])
    transmission.c.change_torrent.assert_called_once_with(HASH, tracker_add=['https://new.example'])
    transmission.c.start_torrent.assert_not_called()
    transmission.c.add_torrent.assert_not_called()


@pytest.mark.parametrize('start', [True, False])
def test_transmission_new_magnet_obeys_start_setting(transmission, start):
    transmission.c.get_torrents.return_value = []
    assert transmission.add_magnet(MAGNET, '/remote/chosen', start) is None
    transmission.c.add_torrent.assert_called_once_with(MAGNET, download_dir='/remote/chosen', paused=not start)


def test_duplicate_created_while_dialog_open_is_not_added_again(transmission):
    transmission.c.get_torrents.return_value = [{'hashString': HASH, 'name': 'Existing', 'trackers': []}]
    assert transmission.add_magnet(MAGNET, '/different/path', True)
    transmission.c.add_torrent.assert_not_called()


def test_transmission_file_selection_sent_with_add(transmission):
    transmission.add_torrent_file(b'torrent', '/remote/chosen', [1, 0, 1])
    transmission.c.add_torrent.assert_called_once_with(b'torrent', download_dir='/remote/chosen', files_wanted=[0, 2], files_unwanted=[1])


def test_base32_duplicate_hash_is_normalized(transmission):
    transmission.c.get_torrents.return_value = []
    transmission.find_magnet_duplicate('magnet:?xt=urn:btih:' + 'A' * 32)
    assert transmission.c.get_torrents.call_args.kwargs['ids'] == ['0' * 40]


def test_inspection_fetches_remote_default_in_worker(frame):
    frame.client.get_default_save_path.return_value = '/server/default'
    frame._show_magnet = Mock()
    frame._inspect_magnet(frame.client, 1, MAGNET)
    frame._show_magnet.assert_called_once_with(frame.client, 1, MAGNET, None, None, '/server/default')


def test_modal_deferral_keeps_queue_busy(frame, monkeypatch):
    frame.IsEnabled.return_value = False
    frame._magnet_busy = True
    later = Mock()
    monkeypatch.setattr(wx, 'CallLater', later)
    frame._show_magnet(frame.client, 1, MAGNET, None, None, '/server/default')
    assert frame._magnet_busy
    later.assert_called_once_with(200, frame._show_magnet, frame.client, 1, MAGNET, None, None, '/server/default')


def test_manual_add_prefills_valid_clipboard_magnet(frame):
    assert frame._clipboard_torrent_value() == MAGNET
    frame._read_clipboard_text.return_value = 'ordinary text'
    assert frame._clipboard_torrent_value() == ''


@pytest.mark.parametrize('url', [
    'https://example.org/file.torrent',
    'HTTP://example.org/FILE.TORRENT?token=keep%2Bthis&x=1#fragment',
    'https://example.org/a%20file%2Etorrent?download=1',
])
def test_prefill_recognizes_torrent_urls_and_preserves_query(frame, url):
    frame._read_clipboard_text.return_value = f'Copy this: <{url}>\n'
    assert frame._clipboard_torrent_value() == url


@pytest.mark.parametrize('text', [
    None, '', 'https://example.org/page', 'https://example.org/file.torrent.exe',
    'https://example.org/?file=a.torrent', 'file:///tmp/a.torrent',
    'ftp://example.org/a.torrent', 'https:///a.torrent',
    'https://example.org:bad/a.torrent', 'https://example.org:0/a.torrent',
    'magnet:?xt=invalid', 'ordinary text',
    pytest.param('x' * (1024 * 1024 + 1), id='oversized'),
])
def test_prefill_ignores_unrecognized_clipboard_content(text):
    assert intake.clipboard_torrent_url(text) == ''


def test_prefill_uses_first_recognizable_link_in_clipboard_order():
    url = 'https://example.org/a.torrent'
    assert intake.clipboard_torrent_url(f'{url}\n{MAGNET}') == url
    assert intake.clipboard_torrent_url(f'{MAGNET}\n{url}') == MAGNET


def test_disabling_prefill_does_not_read_clipboard_or_disable_monitor(frame):
    frame.config_manager.get_preferences.return_value = {'clipboard_prefill': False, 'clipboard_auto_add': True}
    assert frame._clipboard_torrent_value() == ''
    frame._read_clipboard_text.assert_not_called()
    frame._queue_magnet = Mock()
    frame._on_clipboard_timer(None)
    frame._queue_magnet.assert_called_once_with(MAGNET)


def test_prefill_clipboard_error_keeps_dialog_empty(frame):
    frame._read_clipboard_text.side_effect = RuntimeError('clipboard busy')
    assert frame._clipboard_torrent_value() == ''


def test_tracker_merge_failure_reports_error(frame):
    frame.client.add_trackers.side_effect = RuntimeError('offline')
    frame._merge_magnet_trackers(frame.client, 1, HASH, ['https://new.example'])
    frame._on_action_error.assert_called_once_with('offline')


def test_torrent_file_duplicate_uses_same_tracker_prompt_data(transmission, monkeypatch):
    monkeypatch.setattr(clients, "torrent_file_magnet", lambda data: MAGNET)
    transmission.c.get_torrents.return_value = [{
        "hashString": HASH,
        "name": "Existing",
        "trackers": [{"announce": "https://old.example/announce"}],
    }]
    before_add = Mock()

    magnet, duplicate = transmission.add_torrent_file_if_new(
        b"torrent",
        "/remote/chosen",
        [1, 0, 1],
        before_add=before_add,
    )

    assert magnet == MAGNET
    assert duplicate == (
        HASH,
        "Existing",
        ["https://old.example/announce"],
    )
    before_add.assert_not_called()
    transmission.c.add_torrent.assert_not_called()


def test_new_torrent_file_runs_preflight_and_adds_once(transmission, monkeypatch):
    monkeypatch.setattr(clients, "torrent_file_magnet", lambda data: MAGNET)
    transmission.c.get_torrents.return_value = []
    before_add = Mock()

    magnet, duplicate = transmission.add_torrent_file_if_new(
        b"torrent",
        "/remote/chosen",
        [1, 0, 1],
        before_add=before_add,
    )

    assert magnet == MAGNET
    assert duplicate is None
    before_add.assert_called_once_with()
    transmission.c.add_torrent.assert_called_once_with(
        b"torrent",
        download_dir="/remote/chosen",
        files_wanted=[0, 2],
        files_unwanted=[1],
    )
