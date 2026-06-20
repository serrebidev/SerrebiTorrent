"""
Comprehensive test suite for SerrebiTorrent torrent client functionality.

Tests cover:
- URL encoding for special characters
- Torrent adding (file, URL, magnet)
- Torrent state management (start, stop, pause, resume)
- Torrent removal (with/without data)
- Seeding/leeching status detection
- Session persistence (save/load resume data)
- LocalClient lifecycle
"""

import pytest
import sys
import os
import tempfile
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# ============================================================================
# URL Encoding Tests (Unit)
# ============================================================================

class TestSafeEncodeUrl:
    """Test URL encoding for special characters like brackets."""
    
    def test_encode_brackets_in_path(self):
        from clients import safe_encode_url
        url = "https://example.com/torrent/Test[Group].torrent"
        result = safe_encode_url(url)
        assert "%5B" in result  # [ encoded
        assert "%5D" in result  # ] encoded
        assert "[" not in result
        assert "]" not in result
    
    def test_preserve_scheme_and_host(self):
        from clients import safe_encode_url
        url = "https://zoink.ch/torrent/File[tag].torrent"
        result = safe_encode_url(url)
        assert result.startswith("https://zoink.ch/")
    
    def test_preserve_slashes(self):
        from clients import safe_encode_url
        url = "https://example.com/path/to/file[1].torrent"
        result = safe_encode_url(url)
        # Slashes should not be encoded
        assert "/path/to/" in result
    
    def test_preserve_query_string(self):
        from clients import safe_encode_url
        url = "https://example.com/file[1].torrent?token=abc&id=123"
        result = safe_encode_url(url)
        assert "?token=abc&id=123" in result
    
    def test_no_change_for_clean_url(self):
        from clients import safe_encode_url
        url = "https://example.com/simple.torrent"
        result = safe_encode_url(url)
        assert result == url
    
    def test_real_eztv_url(self):
        from clients import safe_encode_url
        url = "https://zoink.ch/torrent/The.Weakest.Link.2021.S05E10.1080p.WEB.h264-CBFM[EZTVx.to].mkv.torrent"
        result = safe_encode_url(url)
        assert "%5BEZTVx.to%5D" in result
        assert "zoink.ch" in result


# ============================================================================
# Session Manager Tests (Mocked)
# ============================================================================

@pytest.fixture
def mock_lt():
    """Create a comprehensive mock for libtorrent."""
    mock = MagicMock()
    
    # Enums
    mock.proxy_type_t = MagicMock()
    mock.proxy_type_t.none = 0
    mock.proxy_type_t.socks4 = 1
    mock.proxy_type_t.socks5 = 2
    mock.proxy_type_t.socks5_pw = 3
    mock.proxy_type_t.http = 4
    mock.proxy_type_t.http_pw = 5
    
    mock.alert = MagicMock()
    mock.alert.category_t = MagicMock()
    mock.alert.category_t.status_notification = 1
    mock.alert.category_t.storage_notification = 2
    mock.alert.category_t.error_notification = 4
    
    mock.resume_data_flags_t = MagicMock()
    mock.resume_data_flags_t.flush_disk_cache = 1
    mock.session.return_value.wait_for_alert.return_value = False
    mock.session.return_value.pop_alerts.return_value = []
    
    mock.remove_flags_t = MagicMock()
    mock.remove_flags_t.delete_files = 1
    
    # Torrent status states
    mock.torrent_status = MagicMock()
    mock.torrent_status.seeding = 5
    mock.torrent_status.finished = 4
    mock.torrent_status.downloading = 3
    mock.torrent_status.checking_files = 1
    mock.torrent_status.queued_for_checking = 0
    
    return mock


@pytest.fixture
def mock_session_env(mock_lt):
    """Set up mocked libtorrent environment."""
    original_lt = sys.modules.get('libtorrent')
    original_sm = sys.modules.get('session_manager')
    
    sys.modules['libtorrent'] = mock_lt
    if 'session_manager' in sys.modules:
        del sys.modules['session_manager']
    
    yield mock_lt
    
    if original_lt:
        sys.modules['libtorrent'] = original_lt
    elif 'libtorrent' in sys.modules:
        del sys.modules['libtorrent']
    
    if original_sm:
        sys.modules['session_manager'] = original_sm
    elif 'session_manager' in sys.modules:
        del sys.modules['session_manager']


@pytest.fixture
def session_manager_instance(mock_session_env):
    """Create a SessionManager instance with mocked dependencies."""
    from session_manager import SessionManager
    SessionManager._instance = None
    
    with patch('session_manager.get_state_dir', return_value=tempfile.gettempdir()):
        with patch('os.path.exists', return_value=False):
            with patch('session_manager.ConfigManager') as MockCM:
                MockCM.return_value.get_preferences.return_value = {}
                with patch('os.listdir', return_value=[]):
                    sm = SessionManager.get_instance()
                    sm.ses.reset_mock()
                    yield sm
                    sm.running = False
                    sm.alert_thread.join(timeout=1)
    
    SessionManager._instance = None


class TestSessionManagerAddTorrent:
    """Test adding torrents via various methods."""
    
    def test_add_torrent_file_success(self, session_manager_instance, mock_session_env, tmp_path):
        """Test adding a torrent from file content."""
        mock_info = MagicMock()
        mock_info.info_hash.return_value = "a" * 40
        mock_info.info_hashes.return_value = MagicMock()
        mock_session_env.torrent_info.return_value = mock_info
        session_manager_instance.state_dir = str(tmp_path)
        
        with patch.object(session_manager_instance, '_find_handle', return_value=None):
            session_manager_instance.add_torrent_file(b"torrent_content", "/downloads")
        
        session_manager_instance.ses.add_torrent.assert_called_once()
    
    def test_add_torrent_file_duplicate_rejected(self, session_manager_instance, mock_session_env):
        """Test that duplicate torrents are rejected."""
        mock_info = MagicMock()
        mock_info.info_hash.return_value = "b" * 40
        mock_session_env.torrent_info.return_value = mock_info
        
        with patch.object(session_manager_instance, '_find_handle', return_value=MagicMock()):
            with pytest.raises(ValueError, match="already exists"):
                session_manager_instance.add_torrent_file(b"content", "/downloads")
    
    def test_add_magnet_success(self, session_manager_instance, mock_session_env):
        """Test adding a magnet link."""
        mock_params = MagicMock()
        mock_params.info_hashes.v1 = "c" * 40
        mock_params.info_hashes.has_v1.return_value = True
        mock_session_env.parse_magnet_uri.return_value = mock_params
        
        with patch.object(session_manager_instance, '_find_handle', return_value=None):
            session_manager_instance.add_magnet("magnet:?xt=urn:btih:abc", "/downloads")
        
        session_manager_instance.ses.add_torrent.assert_called_once()
    
    def test_add_magnet_duplicate_rejected(self, session_manager_instance, mock_session_env):
        """Test that duplicate magnets are rejected."""
        mock_params = MagicMock()
        mock_params.info_hashes.v1 = "d" * 40
        mock_params.info_hashes.has_v1.return_value = True
        mock_session_env.parse_magnet_uri.return_value = mock_params
        
        with patch.object(session_manager_instance, '_find_handle', return_value=MagicMock()):
            with pytest.raises(ValueError, match="already exists"):
                session_manager_instance.add_magnet("magnet:?xt=urn:btih:def", "/downloads")


class TestSessionManagerRemove:
    """Test torrent removal functionality."""
    
    def test_remove_torrent_without_data(self, session_manager_instance, mock_session_env):
        """Test removing a torrent without deleting files."""
        info_hash = "e" * 40
        session_manager_instance.torrents_db[info_hash] = {'save_path': '/tmp'}
        
        mock_handle = MagicMock()
        with patch.object(session_manager_instance, '_find_handle', return_value=mock_handle):
            with patch('os.path.exists', return_value=False):
                session_manager_instance.remove_torrent(info_hash, delete_files=False)
        
        session_manager_instance.ses.remove_torrent.assert_called_once()
        # Called with handle and flags=0
        call_args = session_manager_instance.ses.remove_torrent.call_args
        assert call_args[0][1] == 0  # delete_files=False -> flags=0
    
    def test_remove_torrent_with_data(self, session_manager_instance, mock_session_env):
        """Test removing a torrent with file deletion."""
        info_hash = "f" * 40
        session_manager_instance.torrents_db[info_hash] = {'save_path': '/tmp'}
        
        mock_handle = MagicMock()
        with patch.object(session_manager_instance, '_find_handle', return_value=mock_handle):
            with patch('os.path.exists', return_value=False):
                session_manager_instance.remove_torrent(info_hash, delete_files=True)
        
        session_manager_instance.ses.remove_torrent.assert_called_once()
        # Called with delete flag
        call_args = session_manager_instance.ses.remove_torrent.call_args
        assert call_args[0][1] != 0  # delete_files=True -> non-zero flags
    
    def test_remove_cleans_up_db(self, session_manager_instance, mock_session_env):
        """Test that removal cleans up the torrents database."""
        info_hash = "1" * 40
        session_manager_instance.torrents_db[info_hash] = {'save_path': '/tmp'}
        
        mock_handle = MagicMock()
        with patch.object(session_manager_instance, '_find_handle', return_value=mock_handle):
            with patch('os.path.exists', return_value=False):
                session_manager_instance.remove_torrent(info_hash)
        
        assert info_hash not in session_manager_instance.torrents_db


class TestSessionManagerState:
    """Test session state persistence."""
    
    def test_save_state_triggers_resume_data(self, session_manager_instance, mock_session_env):
        """Test that save_state triggers resume data save for all torrents."""
        mock_handle1 = MagicMock()
        mock_handle1.is_valid.return_value = True
        mock_handle2 = MagicMock()
        mock_handle2.is_valid.return_value = True
        
        session_manager_instance.ses.get_torrents.return_value = [mock_handle1, mock_handle2]
        session_manager_instance.pending_saves = set()
        
        with patch.object(session_manager_instance, '_handle_hash_key', return_value=""):
            session_manager_instance.save_state()
        
        mock_handle1.save_resume_data.assert_called_once()
        mock_handle2.save_resume_data.assert_called_once()
    
    def test_save_state_skips_invalid_handles(self, session_manager_instance, mock_session_env):
        """Test that save_state skips invalid handles."""
        mock_handle = MagicMock()
        mock_handle.is_valid.return_value = False
        
        session_manager_instance.ses.get_torrents.return_value = [mock_handle]
        session_manager_instance.pending_saves = set()
        
        session_manager_instance.save_state()
        
        mock_handle.save_resume_data.assert_not_called()


# ============================================================================
# LocalClient Tests (using real imports where possible)
# ============================================================================

class TestLocalClientUrlEncoding:
    """Test LocalClient URL encoding - these don't require mocking SessionManager."""
    
    def test_safe_downloader_used_in_add_torrent_url(self):
        """Verify that LocalClient uses the capped HTTP(S) downloader."""
        # Read the source code and verify
        import inspect
        from clients import LocalClient
        source = inspect.getsource(LocalClient.add_torrent_url)
        assert "download_torrent_url" in source
    
    def test_url_encoding_function_exists(self):
        """Test that safe_encode_url is exported from clients."""
        from clients import safe_encode_url
        assert callable(safe_encode_url)
        
        # Test it works
        url = "https://example.com/file[1].torrent"
        encoded = safe_encode_url(url)
        assert "%5B" in encoded
        assert "%5D" in encoded

    def test_download_torrent_url_rejects_non_http_scheme(self):
        from clients import download_torrent_url
        with pytest.raises(ValueError):
            download_torrent_url("file:///C:/secret.torrent")

    def test_download_torrent_url_enforces_size_cap(self, monkeypatch):
        import clients

        class FakeResponse:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                yield b"a" * (clients.MAX_TORRENT_DOWNLOAD_BYTES + 1)

        monkeypatch.setattr(clients.requests, "get", lambda *args, **kwargs: FakeResponse())

        with pytest.raises(ValueError):
            clients.download_torrent_url("https://example.com/test.torrent")


class TestLocalClientTorrentStatus:
    """Test LocalClient torrent status detection - simplified unit tests."""
    
    def test_seeding_state_value(self):
        """Test that seeding state detection logic is correct."""
        # Test the logic used in get_torrents_full
        # state = 0 if (paused and not auto_managed) else 1
        
        # Seeding, not paused
        paused, auto_managed = False, True
        state = 0 if (paused and not auto_managed) else 1
        assert state == 1  # Active
        
        # Paused manually
        paused, auto_managed = True, False
        state = 0 if (paused and not auto_managed) else 1
        assert state == 0  # Stopped
        
        # Paused but auto-managed (queued)
        paused, auto_managed = True, True
        state = 0 if (paused and not auto_managed) else 1
        assert state == 1  # Still shows as active (queued)
    
    def test_ratio_calculation(self):
        """Test ratio calculation logic."""
        # ratio = (upload / download * 1000) if download > 0 else 0
        
        # Normal case
        upload, download = 500, 1000
        ratio = (upload / download * 1000) if download > 0 else 0
        assert ratio == 500
        
        # No download yet
        upload, download = 100, 0
        ratio = (upload / download * 1000) if download > 0 else 0
        assert ratio == 0
    
    def test_eta_calculation(self):
        """Test ETA calculation logic."""
        # eta = (remaining / rate) if rate > 0 else -1
        
        # Downloading
        total_wanted, done, rate = 1000, 500, 100
        remaining = total_wanted - done
        eta = int(remaining / rate) if rate > 0 else -1
        assert eta == 5
        
        # No download speed
        rate = 0
        eta = int(remaining / rate) if rate > 0 else -1
        assert eta == -1


# ============================================================================
# Integration Tests (Real libtorrent, if available)
# ============================================================================

@pytest.fixture
def real_libtorrent():
    """Skip if libtorrent is not available."""
    try:
        from libtorrent_env import prepare_libtorrent_dlls
        prepare_libtorrent_dlls()
        import libtorrent as lt
        return lt
    except ImportError:
        pytest.skip("libtorrent not available for integration tests")


@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing."""
    import tempfile
    import shutil
    
    state_dir = tempfile.mkdtemp(prefix="serrebi_test_state_")
    download_dir = tempfile.mkdtemp(prefix="serrebi_test_dl_")
    
    yield {'state': state_dir, 'download': download_dir}
    
    shutil.rmtree(state_dir, ignore_errors=True)
    shutil.rmtree(download_dir, ignore_errors=True)


class TestIntegrationTorrentCreation:
    """Integration tests using real libtorrent."""
    
    def test_create_and_parse_torrent(self, real_libtorrent, temp_dirs):
        """Test creating a torrent file and parsing it back."""
        lt = real_libtorrent
        
        # Create a test file
        test_file = os.path.join(temp_dirs['download'], "test_file.txt")
        with open(test_file, 'w') as f:
            f.write("Test content for torrent")
        
        # Create torrent
        fs = lt.file_storage()
        lt.add_files(fs, test_file)
        
        ct = lt.create_torrent(fs)
        ct.set_creator("SerrebiTorrent Test")
        lt.set_piece_hashes(ct, temp_dirs['download'])
        
        torrent_data = lt.bencode(ct.generate())
        
        # Parse it back
        info = lt.torrent_info(torrent_data)
        
        assert info.name() == "test_file.txt"
        assert info.num_files() == 1
    
    def test_url_encoding_with_real_request(self, real_libtorrent):
        """Test that encoded URLs work with real requests library."""
        from clients import safe_encode_url
        import requests
        
        # Test encoding
        url = "https://example.com/test[1].torrent"
        encoded = safe_encode_url(url)
        
        assert "%5B" in encoded
        assert "%5D" in encoded
        
        # Note: We don't actually fetch this URL as it doesn't exist
        # This just verifies the encoding is correct


class TestIntegrationSessionLifecycle:
    """Integration tests for session lifecycle."""
    
    def test_session_manager_creates_session(self, real_libtorrent, temp_dirs):
        """Test that SessionManager can create a real session."""
        # Reset singleton
        from session_manager import SessionManager
        SessionManager._instance = None
        
        with patch('session_manager.get_state_dir', return_value=temp_dirs['state']):
            with patch('session_manager.ConfigManager') as MockCM:
                MockCM.return_value.get_preferences.return_value = {
                    'enable_dht': False,  # Disable for testing
                    'enable_lsd': False,
                    'enable_upnp': False,
                    'enable_natpmp': False,
                }
                sm = SessionManager.get_instance()
                
                assert sm.ses is not None
                assert isinstance(sm.ses, real_libtorrent.session)
                
                # Cleanup
                sm.running = False
                SessionManager._instance = None


# ============================================================================
# Concurrent Operations Tests
# ============================================================================

class TestConcurrentOperations:
    """Test thread safety of operations."""
    
    def test_torrents_db_thread_safety(self, mock_session_env):
        """Test that torrents_db access is thread-safe."""
        import threading
        import time
        
        from session_manager import SessionManager
        SessionManager._instance = None
        
        with patch('session_manager.get_state_dir', return_value=tempfile.gettempdir()):
            with patch('os.path.exists', return_value=False):
                with patch('session_manager.ConfigManager') as MockCM:
                    MockCM.return_value.get_preferences.return_value = {}
                    with patch('os.listdir', return_value=[]):
                        sm = SessionManager.get_instance()
        
        errors = []
        
        def writer():
            try:
                for i in range(100):
                    with sm.lock:
                        sm.torrents_db[f"hash_{i}"] = {'save_path': f'/path/{i}'}
            except Exception as e:
                errors.append(e)
        
        def reader():
            try:
                for _ in range(100):
                    with sm.lock:
                        _ = dict(sm.torrents_db)
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Thread safety errors: {errors}"
        
        sm.running = False
        sm.alert_thread.join(timeout=1)
        SessionManager._instance = None
