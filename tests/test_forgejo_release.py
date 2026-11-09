import json

import pytest

from tools import forgejo_release
from tools.forgejo_release import (
    ForgejoClient,
    ReleaseError,
    draft_ids,
    main,
    publish,
    verify_latest,
)


class FakeResponse:
    def __init__(self, status_code, payload=None, reason="OK"):
        self.status_code = status_code
        self.reason = reason
        self._payload = payload
        self.content = b"" if payload is None else json.dumps(payload).encode()

    def json(self):
        if self._payload is None:
            raise ValueError("no content")
        return self._payload


class FakeForgejo:
    """In-memory Forgejo releases API."""

    def __init__(self):
        self.base = ""
        self.releases = []
        self.next_id = 4100
        self.uploads = []
        self.fail_uploads = False

    def request(self, method, url, headers=None, params=None, timeout=None, **kwargs):
        body = kwargs.get("json")
        files = kwargs.get("files")
        assert url.startswith(self.base)
        path = url[len(self.base):]
        if method == "GET" and path == "/releases":
            return FakeResponse(200, list(self.releases))
        if method == "GET" and path.startswith("/releases/tags/"):
            tag = path.rsplit("/", 1)[1]
            for release in self.releases:
                if release["tag_name"] == tag:
                    return FakeResponse(200, dict(release))
            return FakeResponse(404, reason="Not Found")
        if method == "GET" and path == "/releases/latest":
            published = [r for r in self.releases if not r.get("draft")]
            if not published:
                return FakeResponse(404, reason="Not Found")
            return FakeResponse(200, dict(max(published, key=lambda r: r["id"])))
        if method == "POST" and path == "/releases":
            release = {
                "id": self.next_id,
                "tag_name": body["tag_name"],
                "name": body["name"],
                "body": body["body"],
                "draft": body["draft"],
                "assets": [],
            }
            self.next_id += 1
            self.releases.append(release)
            return FakeResponse(201, dict(release))
        if method == "PATCH" and path.startswith("/releases/"):
            release = self._find(int(path.rsplit("/", 1)[1]))
            release.update(body)
            return FakeResponse(200, dict(release))
        if method == "DELETE" and path.startswith("/releases/"):
            release_id = int(path.rsplit("/", 1)[1])
            self.releases = [r for r in self.releases if r["id"] != release_id]
            return FakeResponse(204)
        if method == "POST" and path.endswith("/assets"):
            release_id = int(path.split("/")[-2])
            if self.fail_uploads:
                return FakeResponse(500, reason="Internal Server Error")
            field, (filename, handle, _content_type) = next(iter(files.items()))
            handle.read()
            self.uploads.append((release_id, field, filename))
            asset = {"name": filename}
            self._find(release_id)["assets"].append(asset)
            return FakeResponse(201, dict(asset))
        raise AssertionError(f"unexpected call {method} {path}")

    def _find(self, release_id):
        for release in self.releases:
            if release["id"] == release_id:
                return release
        raise AssertionError(f"unknown release {release_id}")


def make_client(fake):
    client = ForgejoClient("forgejo.example", "serrebi/SerrebiTorrent", "token", session=fake)
    fake.base = client.base
    return client


def make_asset(tmp_path, name="pkg.zip", text="data"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_publish_creates_uploads_and_publishes(tmp_path):
    fake = FakeForgejo()
    client = make_client(fake)
    assets = [make_asset(tmp_path, "a.zip"), make_asset(tmp_path, "b.json")]

    release = publish(client, "v9.9.9", "V9.9.9", "notes", assets)

    assert release["tag_name"] == "v9.9.9"
    stored = fake.releases[0]
    assert stored["draft"] is False
    assert [a["name"] for a in stored["assets"]] == ["a.zip", "b.json"]
    assert fake.uploads == [
        (stored["id"], forgejo_release.ATTACHMENT_FIELD, "a.zip"),
        (stored["id"], forgejo_release.ATTACHMENT_FIELD, "b.json"),
    ]
    verify_latest(client, "v9.9.9")


def test_publish_sweeps_unrelated_drafts(tmp_path):
    fake = FakeForgejo()
    fake.releases.append({"id": 1, "tag_name": "v0.0.1", "draft": True, "assets": []})
    fake.releases.append({"id": 2, "tag_name": "v0.0.2", "draft": False, "assets": []})
    client = make_client(fake)

    publish(client, "v9.9.9", "V9.9.9", "notes", [make_asset(tmp_path)])

    assert sorted(r["id"] for r in fake.releases) == [2, 4100]


def test_publish_replaces_stale_draft_for_same_tag(tmp_path):
    fake = FakeForgejo()
    fake.releases.append({"id": 7, "tag_name": "v9.9.9", "draft": True, "assets": []})
    client = make_client(fake)

    publish(client, "v9.9.9", "V9.9.9", "notes", [make_asset(tmp_path)])

    assert [r["id"] for r in fake.releases] == [4100]


def test_publish_refuses_to_overwrite_published_release(tmp_path):
    fake = FakeForgejo()
    fake.releases.append({"id": 3, "tag_name": "v9.9.9", "draft": False, "assets": []})
    client = make_client(fake)

    with pytest.raises(ReleaseError, match="already published"):
        publish(client, "v9.9.9", "V9.9.9", "notes", [make_asset(tmp_path)])
    assert [r["id"] for r in fake.releases] == [3]


def test_failed_upload_deletes_the_created_draft(tmp_path):
    fake = FakeForgejo()
    fake.fail_uploads = True
    client = make_client(fake)

    with pytest.raises(ReleaseError, match="uploading"):
        publish(client, "v9.9.9", "V9.9.9", "notes", [make_asset(tmp_path)])
    assert fake.releases == []


def test_verify_latest_mismatch_warns_about_stale_updater():
    fake = FakeForgejo()
    fake.releases.append({"id": 5, "tag_name": "v9.9.8", "draft": False, "assets": []})
    client = make_client(fake)

    with pytest.raises(ReleaseError, match="updater will keep reporting the old release"):
        verify_latest(client, "v9.9.9")


def test_draft_ids_only_lists_drafts():
    releases = [{"id": 1, "draft": True}, {"id": 2, "draft": False}, {"id": 3}]
    assert draft_ids(releases) == [1]


def test_main_requires_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FORGEJO_TOKEN", raising=False)
    notes = tmp_path / "notes.txt"
    notes.write_text("notes")
    asset = make_asset(tmp_path)

    code = main([
        "--host", "h", "--repo", "r", "--tag", "v1", "--title", "V1",
        "--notes-file", str(notes), "--assets", str(asset),
    ])

    assert code == 1
    assert "FORGEJO_TOKEN is not set" in capsys.readouterr().err


def test_main_rejects_missing_asset(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGEJO_TOKEN", "token")
    notes = tmp_path / "notes.txt"
    notes.write_text("notes")

    code = main([
        "--host", "h", "--repo", "r", "--tag", "v1", "--title", "V1",
        "--notes-file", str(notes), "--assets", str(tmp_path / "missing.zip"),
    ])

    assert code == 1
    assert "asset not found" in capsys.readouterr().err
