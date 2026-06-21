import io
import ipaddress

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
        session["auth_fingerprint"] = web_server._credentials_fingerprint()
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


def test_torrents_add_downloads_http_urls_server_side(app_client, fake_client, monkeypatch):
    monkeypatch.setattr(web_server, "_validate_add_url", lambda u: None)
    monkeypatch.setattr(web_server, "download_torrent_url", lambda u: b"torrent-bytes")
    res = app_client.post(
        "/api/v2/torrents/add",
        data={"urls": "http://example.com/test.torrent", "savepath": "C:\\Downloads"},
        headers=csrf_headers(),
    )
    assert res.status_code == 200
    assert fake_client.urls == []
    assert fake_client.files == [(b"torrent-bytes", "C:\\Downloads")]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/test.torrent",
        "http://127.0.0.1/test.torrent",
        "http://10.0.0.1/test.torrent",
        "http://172.16.0.1/test.torrent",
        "http://192.168.0.1/test.torrent",
        "http://169.254.1.1/test.torrent",
        "http://[::1]/test.torrent",
        "http://[fd00::1]/test.torrent",
    ],
)
def test_torrents_add_rejects_local_and_private_urls_before_client(app_client, fake_client, url):
    res = app_client.post(
        "/api/v2/torrents/add",
        data={"urls": url},
        headers=csrf_headers(),
    )

    assert res.status_code == 400
    assert fake_client.urls == []


def test_torrents_add_rejects_dns_private_host_before_client(app_client, fake_client, monkeypatch):
    monkeypatch.setattr(
        web_server,
        "_resolve_add_host",
        lambda host, port: (ipaddress.ip_address("192.168.1.50"),),
    )

    res = app_client.post(
        "/api/v2/torrents/add",
        data={"urls": "http://private.example/test.torrent"},
        headers=csrf_headers(),
    )

    assert res.status_code == 400
    assert fake_client.urls == []


def test_torrents_add_rejects_redirect_to_private_host_before_client(app_client, fake_client, monkeypatch):
    calls = []

    class RedirectResponse:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/test.torrent"}

        def close(self):
            pass

    monkeypatch.setattr(
        web_server,
        "_resolve_add_host",
        lambda host, port: (ipaddress.ip_address("93.184.216.34"),),
    )

    def fake_get(url, **kwargs):
        calls.append(url)
        return RedirectResponse()

    monkeypatch.setattr(web_server.requests, "get", fake_get)

    res = app_client.post(
        "/api/v2/torrents/add",
        data={"urls": "http://example.com/test.torrent"},
        headers=csrf_headers(),
    )

    assert res.status_code == 400
    assert calls == ["http://example.com/test.torrent"]
    assert fake_client.urls == []


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
            data={"urls": "magnet:?xt=urn:btih:abc"},
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
