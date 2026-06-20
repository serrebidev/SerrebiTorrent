import io

import pytest

import web_server


class FakeClient:
    def __init__(self):
        self.urls = []
        self.files = []

    def add_torrent_url(self, u, sp=None):
        self.urls.append((u, sp))

    def add_torrent_file(self, content, sp=None):
        self.files.append((content, sp))


class FailingClient(FakeClient):
    def add_torrent_url(self, u, sp=None):
        raise RuntimeError("boom")


@pytest.fixture
def app_client():
    client = web_server.app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["csrf_token"] = "test-csrf"
    return client


def csrf_headers():
    return {"X-CSRF-Token": "test-csrf"}


@pytest.fixture
def fake_client():
    original = web_server.WEB_CONFIG["client"]
    client = FakeClient()
    web_server.WEB_CONFIG["client"] = client
    yield client
    web_server.WEB_CONFIG["client"] = original


def test_torrents_add_calls_client_for_urls(app_client, fake_client):
    res = app_client.post(
        "/api/v2/torrents/add",
        data={"urls": "http://example.com/test.torrent", "savepath": "C:\\Downloads"},
        headers=csrf_headers(),
    )
    assert res.status_code == 200
    assert fake_client.urls == [("http://example.com/test.torrent", "C:\\Downloads")]


def test_torrents_add_calls_client_for_files(app_client, fake_client):
    data = {
        "savepath": "C:\\Downloads",
        "torrents": (io.BytesIO(b"abc"), "test.torrent"),
    }
    res = app_client.post(
        "/api/v2/torrents/add",
        data=data,
        content_type="multipart/form-data",
        headers=csrf_headers(),
    )
    assert res.status_code == 200
    assert fake_client.files == [(b"abc", "C:\\Downloads")]


def test_torrents_add_returns_error_on_failure(app_client):
    original = web_server.WEB_CONFIG["client"]
    web_server.WEB_CONFIG["client"] = FailingClient()
    try:
        res = app_client.post(
            "/api/v2/torrents/add",
            data={"urls": "http://example.com/test.torrent"},
            headers=csrf_headers(),
        )
        assert res.status_code == 500
        assert b"Failed to add torrents" in res.data
    finally:
        web_server.WEB_CONFIG["client"] = original


def test_torrents_add_rejects_empty_payload(app_client, fake_client):
    res = app_client.post("/api/v2/torrents/add", data={"urls": "   "}, headers=csrf_headers())
    assert res.status_code == 400


def test_torrents_add_requires_csrf(app_client, fake_client):
    res = app_client.post(
        "/api/v2/torrents/add",
        data={"urls": "http://example.com/test.torrent"},
    )
    assert res.status_code == 403
    assert fake_client.urls == []
