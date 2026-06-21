
import pytest
import sys
import os
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import web_server

@pytest.fixture
def client():
    web_server.app.config['TESTING'] = True
    web_server.app.config['SECRET_KEY'] = 'test'
    with web_server.app.test_client() as client:
        yield client

@pytest.fixture
def auth_client(client):
    # Perform login
    client.post('/api/v2/auth/login', data={'username': 'admin', 'password': 'password'})
    return client


def csrf_headers(client):
    with client.session_transaction() as session:
        return {'X-CSRF-Token': session['csrf_token']}

def test_login(client):
    rv = client.post('/api/v2/auth/login', data={'username': 'admin', 'password': 'password'})
    assert b"Ok." in rv.data
    assert rv.status_code == 200
    
    rv = client.post('/api/v2/auth/login', data={'username': 'admin', 'password': 'wrong'})
    assert rv.status_code == 403


def test_session_invalidates_after_credentials_change(client):
    original = web_server.WEB_CONFIG.copy()
    try:
        web_server.WEB_CONFIG.update({'username': 'admin', 'password': 'password'})
        rv = client.post('/api/v2/auth/login', data={'username': 'admin', 'password': 'password'})
        assert rv.status_code == 200

        web_server.WEB_CONFIG.update({'password': 'new-secret'})
        rv = client.get('/api/v2/auth/csrf')

        assert rv.status_code == 403
        with client.session_transaction() as session:
            assert 'logged_in' not in session
            assert 'auth_fingerprint' not in session
    finally:
        web_server.WEB_CONFIG.update(original)


def test_web_ui_does_not_start_with_default_password(monkeypatch):
    original = web_server.WEB_CONFIG.copy()
    original_thread = web_server.server_thread
    thread_ctor = MagicMock()
    try:
        web_server.WEB_CONFIG.update({'password': 'password', 'enabled': True})
        web_server.server_thread = None
        monkeypatch.setattr(web_server.threading, 'Thread', thread_ctor)

        web_server.start_web_ui()

        thread_ctor.assert_not_called()
        assert web_server.server_thread is None
    finally:
        web_server.WEB_CONFIG.update(original)
        web_server.server_thread = original_thread

def test_profiles_endpoint(auth_client):
    mock_app = MagicMock()
    mock_app.config_manager.get_profiles.return_value = {'p1': {'name': 'Profile 1'}}
    mock_app.current_profile_id = 'p1'
    
    web_server.WEB_CONFIG['app'] = mock_app
    
    rv = auth_client.get('/api/v2/profiles')
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert 'p1' in data['profiles']
    assert data['current_id'] == 'p1'

def test_torrents_info_endpoint(auth_client):
    mock_app = MagicMock()
    torrents_list = [
        {'hash': 'abc', 'name': 'Test', 'size': 1000, 'done': 500, 'state': 1}
    ]
    mock_app.all_torrents = torrents_list
    mock_app.get_all_torrents_safe.return_value = torrents_list
    
    web_server.WEB_CONFIG['app'] = mock_app
    
    rv = auth_client.get('/api/v2/torrents/info')
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert len(data['torrents']) == 1
    assert data['stats']['All'] == 1
    assert data['stats']['Downloading'] == 1

def test_torrents_add_endpoint(auth_client):
    mock_client = MagicMock()
    web_server.WEB_CONFIG['client'] = mock_client
    
    rv = auth_client.post(
        '/api/v2/torrents/add',
        data={'urls': 'magnet:?foo', 'savepath': '/tmp'},
        headers=csrf_headers(auth_client),
    )
    assert rv.status_code == 200
    mock_client.add_torrent_url.assert_called_with('magnet:?foo', sp='/tmp')

def test_rss_feeds_endpoint(auth_client):
    mock_app = MagicMock()
    mock_app.rss_panel.manager.feeds = {'http://feed': {'alias': 'Test'}}
    web_server.WEB_CONFIG['app'] = mock_app
    
    rv = auth_client.get('/api/v2/rss/feeds')
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert 'http://feed' in data
