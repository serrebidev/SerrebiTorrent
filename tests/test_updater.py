
import pytest
import sys
import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import updater
from updater import (
    parse_semver,
    format_version,
    is_newer_version,
    _is_sha256,
    validate_manifest,
    UpdateError,
    UpdateInfo,
    check_for_updates,
    check_for_update,
    download_file,
    download_manifest,
    download_and_apply_update,
    extract_zip,
    launch_update_helper,
    find_update_helper,
    get_allowed_thumbprints,
    verify_authenticode,
    APP_VERSION
)

ASSET_URL = "https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/download/v1.0.0/app.zip"
SIGNING_THUMBPRINT = "A" * 40


class _FakeResponse:
    """Minimal streaming-response stand-in for updater network tests."""

    def __init__(self, status_code=200, chunks=(), headers=None, url=None):
        self.status_code = status_code
        self.reason = "OK"
        self.headers = dict(headers or {})
        self.url = url
        self._chunks = list(chunks)

    def iter_content(self, chunk_size):
        yield from self._chunks

    def close(self):
        pass



class FakeStartupInfo:
    def __init__(self):
        self.dwFlags = 0
        self.wShowWindow = None


@pytest.fixture
def windows_subprocess(monkeypatch):
    """Simulate Windows well enough to exercise the hidden-window paths.

    These paths only run on Windows, but the Linux and macOS builders run the
    same suite, and POSIX subprocess does not define STARTUPINFO or the
    creation flags. Supply the missing names so the behaviour stays covered
    everywhere instead of being skipped off Windows.
    """
    monkeypatch.setattr(updater.sys, "platform", "win32")
    defaults = {
        "STARTF_USESHOWWINDOW": 1,
        "CREATE_NO_WINDOW": 0x08000000,
        "CREATE_NEW_PROCESS_GROUP": 0x00000200,
        "CREATE_BREAKAWAY_FROM_JOB": 0x01000000,
        "STARTUPINFO": FakeStartupInfo,
    }
    for name, value in defaults.items():
        if not hasattr(updater.subprocess, name):
            monkeypatch.setattr(updater.subprocess, name, value, raising=False)
    return updater.subprocess


def release_with_asset(tag="v1.0.0", url=ASSET_URL, digest=None):
    asset = {
        "name": "app.zip",
        "browser_download_url": url,
    }
    if digest is not None:
        asset["digest"] = digest
    return {
        "tag_name": tag,
        "assets": [asset],
    }


def test_parse_semver():
    assert parse_semver("1.0.0") == (1, 0, 0)
    assert parse_semver("v1.2.3") == (1, 2, 3)
    assert parse_semver("2.0") is None
    assert parse_semver("1.2.3-rc1") is None
    assert parse_semver("1.2.3.4") is None
    assert parse_semver("") is None

def test_format_version():
    assert format_version((1, 2, 3)) == "1.2.3"

def test_is_newer_version():
    assert is_newer_version((1, 0, 0), (1, 0, 1)) is True
    assert is_newer_version((1, 0, 0), (2, 0, 0)) is True
    assert is_newer_version((1, 1, 0), (1, 0, 1)) is False
    assert is_newer_version((1, 0, 0), (1, 0, 0)) is False

def test_is_sha256():
    valid_sha = "a" * 64
    assert _is_sha256(valid_sha) is True
    assert _is_sha256("short") is False
    assert _is_sha256("z" * 64) is False # Not hex

def test_validate_manifest_success():
    release = release_with_asset()
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": ASSET_URL,
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    validated = validate_manifest(manifest, release)
    assert validated == manifest

def test_validate_manifest_accepts_matching_release_asset_digest():
    release = release_with_asset(digest="sha256:" + "A" * 64)
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": ASSET_URL,
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    assert validate_manifest(manifest, release) == manifest


def test_validate_manifest_rejects_mismatched_release_asset_digest():
    release = release_with_asset(digest="sha256:" + "b" * 64)
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": ASSET_URL,
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    with pytest.raises(UpdateError):
        validate_manifest(manifest, release)


def test_validate_manifest_rejects_malformed_release_asset_digest():
    release = release_with_asset(digest="sha256:not-a-checksum")
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": ASSET_URL,
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    with pytest.raises(UpdateError):
        validate_manifest(manifest, release)


def test_validate_manifest_tolerates_release_without_digest():
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": ASSET_URL,
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    assert validate_manifest(manifest, release_with_asset()) == manifest


def test_validate_manifest_ignores_non_sha256_release_asset_digest():
    release = release_with_asset(digest="sha512:" + "c" * 128)
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": ASSET_URL,
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    assert validate_manifest(manifest, release) == manifest


def test_validate_manifest_missing_fields():
    release = release_with_asset()
    manifest = {
        "version": "1.0.0"
    }
    with pytest.raises(UpdateError):
        validate_manifest(manifest, release)

def test_validate_manifest_version_mismatch():
    release = release_with_asset(tag="v1.0.1")
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": "https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/download/v1.0.1/app.zip",
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    with pytest.raises(UpdateError):
        validate_manifest(manifest, release)


def test_validate_manifest_rejects_invalid_manifest_semver():
    release = release_with_asset()
    manifest = {
        "version": "1.0",
        "asset_filename": "app.zip",
        "download_url": ASSET_URL,
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    with pytest.raises(UpdateError):
        validate_manifest(manifest, release)


def test_validate_manifest_rejects_invalid_published_at():
    release = release_with_asset()
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": ASSET_URL,
        "sha256": "a" * 64,
        "published_at": "not-a-date",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    with pytest.raises(UpdateError):
        validate_manifest(manifest, release)


def test_validate_manifest_rejects_non_forgejo_download_url():
    release = release_with_asset()
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": "https://example.com/app.zip",
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    with pytest.raises(UpdateError):
        validate_manifest(manifest, release)


def test_validate_manifest_rejects_release_asset_mismatch():
    release = release_with_asset()
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": "https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/download/v1.0.0/other.zip",
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    with pytest.raises(UpdateError):
        validate_manifest(manifest, release)


def test_manifest_thumbprints_are_trusted(monkeypatch):
    manifest = {"signing_thumbprint": "AA BB"}
    monkeypatch.delenv("SERREBITORRENT_TRUSTED_SIGNING_THUMBPRINTS", raising=False)

    assert get_allowed_thumbprints(manifest) == ("AABB",)


def test_env_thumbprints_are_trusted(monkeypatch):
    manifest = {"signing_thumbprint": "AA BB"}
    monkeypatch.setenv("SERREBITORRENT_TRUSTED_SIGNING_THUMBPRINTS", "CC DD")

    assert get_allowed_thumbprints(manifest) == ("AABB", "CCDD")


def test_verify_authenticode_allows_numeric_unknownerror_with_matching_thumbprint(monkeypatch):
    result = MagicMock()
    result.returncode = 0
    result.stdout = '{"Status":1,"StatusMessage":"chain not trusted","Thumbprint":"AA BB"}'
    result.stderr = ""
    monkeypatch.setattr("updater.subprocess.run", lambda *args, **kwargs: result)

    verify_authenticode("SerrebiTorrent.exe", ["AABB"])


def test_verify_authenticode_tries_next_powershell(monkeypatch):
    failed = MagicMock()
    failed.returncode = 1
    failed.stdout = ""
    failed.stderr = "Get-AuthenticodeSignature not found"
    succeeded = MagicMock()
    succeeded.returncode = 0
    succeeded.stderr = ""
    succeeded.stdout = '{"Status":"UnknownError","StatusMessage":"self-signed","Thumbprint":"AA BB"}'

    monkeypatch.setattr(updater, "_powershell_executables", lambda: ("bad-powershell", "pwsh"))
    run = MagicMock(side_effect=[failed, succeeded])
    monkeypatch.setattr(updater.subprocess, "run", run)

    verify_authenticode("SerrebiTorrent.exe", ["AABB"])

    assert run.call_count == 2
    assert run.call_args_list[0].args[0][0] == "bad-powershell"
    assert run.call_args_list[1].args[0][0] == "pwsh"


def test_verify_authenticode_requires_allowed_thumbprint():
    with pytest.raises(UpdateError):
        verify_authenticode("SerrebiTorrent.exe", [])


def test_verify_authenticode_rejects_valid_signature_with_wrong_thumbprint(monkeypatch):
    result = MagicMock()
    result.returncode = 0
    result.stdout = '{"Status":"Valid","StatusMessage":"","Thumbprint":"CC DD"}'
    result.stderr = ""
    monkeypatch.setattr("updater.subprocess.run", lambda *args, **kwargs: result)

    with pytest.raises(UpdateError):
        verify_authenticode("SerrebiTorrent.exe", ["AABB"])


def test_download_file_rejects_content_length_over_limit(monkeypatch, tmp_path):
    class FakeResponse:
        status_code = 200
        reason = "OK"
        headers = {"Content-Length": "5"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_content(self, chunk_size):
            yield b"12345"

    dest = tmp_path / "app.zip"
    monkeypatch.setattr(updater, "MAX_UPDATE_DOWNLOAD_BYTES", 4)
    monkeypatch.setattr(updater.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(UpdateError):
        download_file(ASSET_URL, str(dest))

    assert not dest.exists()


def test_download_file_rejects_stream_over_limit(monkeypatch, tmp_path):
    class FakeResponse:
        status_code = 200
        reason = "OK"
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_content(self, chunk_size):
            yield b"123"
            yield b"45"

    dest = tmp_path / "app.zip"
    monkeypatch.setattr(updater, "MAX_UPDATE_DOWNLOAD_BYTES", 4)
    monkeypatch.setattr(updater.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(UpdateError):
        download_file(ASSET_URL, str(dest))

    assert not dest.exists()


def test_extract_zip_rejects_large_member(monkeypatch, tmp_path):
    zip_path = tmp_path / "app.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("SerrebiTorrent/big.bin", b"12345")

    monkeypatch.setattr(updater, "MAX_UPDATE_ZIP_MEMBER_BYTES", 4)

    with pytest.raises(UpdateError):
        extract_zip(str(zip_path), str(tmp_path / "out"))


def test_extract_zip_rejects_large_uncompressed_total(monkeypatch, tmp_path):
    zip_path = tmp_path / "app.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("SerrebiTorrent/a.bin", b"123")
        zf.writestr("SerrebiTorrent/b.bin", b"456")

    monkeypatch.setattr(updater, "MAX_UPDATE_ZIP_MEMBER_BYTES", 10)
    monkeypatch.setattr(updater, "MAX_UPDATE_ZIP_UNCOMPRESSED_BYTES", 5)

    with pytest.raises(UpdateError):
        extract_zip(str(zip_path), str(tmp_path / "out"))


def test_extract_zip_rejects_too_many_members(monkeypatch, tmp_path):
    zip_path = tmp_path / "app.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("SerrebiTorrent/a.bin", b"")
        zf.writestr("SerrebiTorrent/b.bin", b"")

    monkeypatch.setattr(updater, "MAX_UPDATE_ZIP_MEMBERS", 1)

    with pytest.raises(UpdateError):
        extract_zip(str(zip_path), str(tmp_path / "out"))


def test_download_manifest_rejects_large_content_length(monkeypatch):
    release = {
        "assets": [
            {
                "name": updater.UPDATE_MANIFEST_ASSET,
                "browser_download_url": "https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/download/v1.0.0/SerrebiTorrent-update.json",
            }
        ]
    }

    class FakeResponse:
        status_code = 200
        headers = {"Content-Length": "5"}

        def iter_content(self, chunk_size):
            yield b"{}"

        def close(self):
            pass

    monkeypatch.setattr(updater, "MAX_UPDATE_MANIFEST_BYTES", 4)
    monkeypatch.setattr(updater.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(UpdateError):
        download_manifest(release)


def test_validate_manifest_rejects_missing_signing_thumbprint():
    release = release_with_asset()
    manifest = {
        "version": "1.0.0",
        "asset_filename": "app.zip",
        "download_url": ASSET_URL,
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
    }

    with pytest.raises(UpdateError):
        validate_manifest(manifest, release)


@patch('updater.fetch_latest_release')
@patch('updater.download_manifest')
def test_check_for_update_available(mock_download, mock_fetch):
    url = "https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/download/v99.99.99/app.zip"
    mock_fetch.return_value = release_with_asset(tag="v99.99.99", url=url) # Definitely newer
    mock_download.return_value = {
        "version": "99.99.99",
        "asset_filename": "app.zip",
        "download_url": url,
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }
    
    # We rely on APP_VERSION being importable and smaller than 99.99.99
    update_info = check_for_update()
    assert update_info is not None
    assert update_info.latest_version == "99.99.99"


@patch('updater.fetch_latest_release')
@patch('updater.download_manifest')
def test_check_for_updates_returns_result_object(mock_download, mock_fetch):
    url = "https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/download/v99.99.99/app.zip"
    mock_fetch.return_value = release_with_asset(tag="v99.99.99", url=url)
    mock_download.return_value = {
        "version": "99.99.99",
        "asset_filename": "app.zip",
        "download_url": url,
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }

    result = check_for_updates()

    assert result.status == "update_available"
    assert result.info is not None
    assert result.info.latest_version == "99.99.99"

@patch('updater.fetch_latest_release')
def test_check_for_update_none(mock_fetch):
    mock_fetch.return_value = release_with_asset(tag="v0.0.0") # Very old
    update_info = check_for_update()
    assert update_info is None


def test_launch_update_helper_is_hidden_and_uses_helper_cwd(monkeypatch, tmp_path, windows_subprocess):
    helper = tmp_path / "update_helper.bat"
    helper.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("COMSPEC", "cmd.exe")
    popen = MagicMock()
    monkeypatch.setattr(updater.subprocess, "Popen", popen)

    ok, msg = launch_update_helper(str(helper), 1234, r"C:\Install", r"C:\Stage", temp_root=r"C:\Temp\SerrebiTorrent_update_x")

    assert ok, msg
    args, kwargs = popen.call_args
    assert args[0][:3] == ["cmd.exe", "/d", "/c"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["creationflags"] & 0x08000000
    assert kwargs["creationflags"] & 0x00000200
    assert kwargs["creationflags"] & 0x01000000
    assert kwargs["startupinfo"].dwFlags & updater.subprocess.STARTF_USESHOWWINDOW
    assert kwargs["startupinfo"].wShowWindow == 0
    assert kwargs["stdin"] is updater.subprocess.DEVNULL
    assert kwargs["stdout"] is updater.subprocess.DEVNULL
    assert kwargs["stderr"] is updater.subprocess.DEVNULL


def test_launch_update_helper_retry_keeps_hidden_flags_without_breakaway(monkeypatch, tmp_path, windows_subprocess):
    helper = tmp_path / "update_helper.bat"
    helper.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("COMSPEC", "cmd.exe")
    popen = MagicMock(side_effect=[OSError("job denied"), MagicMock()])
    monkeypatch.setattr(updater.subprocess, "Popen", popen)

    ok, msg = launch_update_helper(str(helper), 1234, r"C:\Install", r"C:\Stage")

    assert ok, msg
    first = popen.call_args_list[0].kwargs["creationflags"]
    second = popen.call_args_list[1].kwargs["creationflags"]
    assert first & 0x01000000
    assert second & 0x08000000
    assert second & 0x00000200
    assert not (second & 0x01000000)
    assert popen.call_args_list[1].kwargs["startupinfo"].wShowWindow == 0


def test_verify_authenticode_runs_powershell_hidden(monkeypatch, windows_subprocess):
    startup = MagicMock()
    monkeypatch.setattr(updater.subprocess, "STARTUPINFO", lambda: startup, raising=False)
    monkeypatch.setattr(updater.subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(updater.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(updater, "_powershell_executables", lambda: ("powershell.exe",))
    result = MagicMock(
        returncode=0,
        stdout='{"Status":"Valid","StatusMessage":"","Subject":"","Thumbprint":"' + SIGNING_THUMBPRINT + '"}',
        stderr="",
    )
    run = MagicMock(return_value=result)
    monkeypatch.setattr(updater.subprocess, "run", run)

    verify_authenticode("SerrebiTorrent.exe", (SIGNING_THUMBPRINT,))

    _args, kwargs = run.call_args
    assert "Get-AuthenticodeSignature -LiteralPath" in _args[0][-1]
    assert "Get-AuthenticodeSignature -FilePath" not in _args[0][-1]
    assert kwargs["creationflags"] == 0x08000000
    assert kwargs["startupinfo"] is startup
    assert startup.dwFlags & 1
    assert startup.wShowWindow == 0


def test_find_update_helper_checks_pyinstaller_internal_dir(tmp_path):
    install = tmp_path / "SerrebiTorrent"
    internal = install / "_internal"
    internal.mkdir(parents=True)
    helper = internal / "update_helper.bat"
    helper.write_text("@echo off\n", encoding="utf-8")

    assert find_update_helper(str(install)) == str(helper)


def test_cleanup_update_artifacts_respects_backup_retention_and_grace(monkeypatch, tmp_path):
    install = tmp_path / "SerrebiTorrent"
    install.mkdir()
    old_backup = tmp_path / "SerrebiTorrent_backup_20260101000000"
    kept_backup = tmp_path / "SerrebiTorrent_backup_20260102000000"
    grace_backup = tmp_path / "SerrebiTorrent_backup_20260103000000"
    for path in (old_backup, kept_backup, grace_backup):
        path.mkdir()
    os.utime(old_backup, (1000, 1000))
    os.utime(kept_backup, (2800, 2800))
    os.utime(grace_backup, (2900, 2900))
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setenv("SERREBITORRENT_KEEP_BACKUPS", "1")

    updater.cleanup_update_artifacts(str(install), now=3000)

    assert not old_backup.exists()
    assert kept_backup.exists()
    assert grace_backup.exists()


def test_cleanup_update_artifacts_removes_all_backups_when_keep_zero(monkeypatch, tmp_path):
    install = tmp_path / "SerrebiTorrent"
    install.mkdir()
    backup = tmp_path / "SerrebiTorrent_backup_20260101000000"
    backup.mkdir()
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setenv("SERREBITORRENT_KEEP_BACKUPS", "0")

    updater.cleanup_update_artifacts(str(install), now=3000)

    assert not backup.exists()


def test_download_and_apply_update_launches_helper_from_temp(monkeypatch, tmp_path):
    install = tmp_path / "SerrebiTorrent"
    install.mkdir()
    (install / "update_helper.bat").write_text("@echo off\n", encoding="utf-8")
    temp_root = tmp_path / "_SerrebiTorrent_update_tmp" / "SerrebiTorrent_update_1"
    extract = temp_root / "extract"
    new_dir = extract / "SerrebiTorrent"
    new_dir.mkdir(parents=True)
    (new_dir / updater.APP_EXE_NAME).write_text("exe", encoding="utf-8")
    info = UpdateInfo(
        current_version="1.0.0",
        latest_version="2.0.0",
        manifest={
            "asset_filename": "app.zip",
            "download_url": ASSET_URL,
            "sha256": "abc",
            "signing_thumbprint": SIGNING_THUMBPRINT,
        },
        release={},
    )

    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_make_update_temp_root", lambda _: str(temp_root))
    monkeypatch.setattr(updater, "download_file", lambda url, dest, progress_cb=None: Path(dest).write_bytes(b"zip"))
    monkeypatch.setattr(updater, "compute_sha256", lambda path: "abc")
    monkeypatch.setattr(updater, "extract_zip", lambda zip_path, dest_dir: None)
    monkeypatch.setattr(updater, "verify_authenticode", lambda exe, thumbs: None)
    launched = {}
    monkeypatch.setattr(
        updater,
        "launch_update_helper",
        lambda helper, pid, inst, staging, temp_root=None: launched.update(
            {"helper": helper, "install": inst, "staging": staging, "temp_root": temp_root}
        ) or (True, ""),
    )

    ok, msg = download_and_apply_update(info, str(install))

    assert ok, msg
    assert launched["install"] == str(install)
    assert launched["staging"] == str(new_dir)
    assert launched["temp_root"] == str(temp_root)
    assert launched["helper"] == str(temp_root / "update_helper.bat")


def test_download_and_apply_update_can_use_internal_update_helper(monkeypatch, tmp_path):
    install = tmp_path / "SerrebiTorrent"
    (install / "_internal").mkdir(parents=True)
    (install / "_internal" / "update_helper.bat").write_text("old-helper\n", encoding="utf-8")
    temp_root = tmp_path / "_SerrebiTorrent_update_tmp" / "SerrebiTorrent_update_1"
    extract = temp_root / "extract"
    new_dir = extract / "SerrebiTorrent"
    (new_dir / "_internal").mkdir(parents=True)
    (new_dir / updater.APP_EXE_NAME).write_text("exe", encoding="utf-8")
    (new_dir / "_internal" / "update_helper.bat").write_text("new-helper\n", encoding="utf-8")
    info = UpdateInfo(
        current_version="1.0.0",
        latest_version="2.0.0",
        manifest={
            "asset_filename": "app.zip",
            "download_url": ASSET_URL,
            "sha256": "abc",
            "signing_thumbprint": SIGNING_THUMBPRINT,
        },
        release={},
    )

    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_make_update_temp_root", lambda _: str(temp_root))
    monkeypatch.setattr(updater, "download_file", lambda url, dest, progress_cb=None: Path(dest).write_bytes(b"zip"))
    monkeypatch.setattr(updater, "compute_sha256", lambda path: "abc")
    monkeypatch.setattr(updater, "extract_zip", lambda zip_path, dest_dir: None)
    monkeypatch.setattr(updater, "verify_authenticode", lambda exe, thumbs: None)
    launched = {}
    monkeypatch.setattr(
        updater,
        "launch_update_helper",
        lambda helper, pid, inst, staging, temp_root=None: launched.update({"helper": helper}) or (True, ""),
    )

    ok, msg = download_and_apply_update(info, str(install))

    assert ok, msg
    assert Path(launched["helper"]).read_text(encoding="utf-8") == "new-helper\n"


def test_download_and_apply_update_reports_progress(monkeypatch, tmp_path):
    install = tmp_path / "SerrebiTorrent"
    install.mkdir()
    (install / "update_helper.bat").write_text("@echo off\n", encoding="utf-8")
    temp_root = tmp_path / "_SerrebiTorrent_update_tmp" / "SerrebiTorrent_update_1"
    extract = temp_root / "extract"
    new_dir = extract / "SerrebiTorrent"
    new_dir.mkdir(parents=True)
    (new_dir / updater.APP_EXE_NAME).write_text("exe", encoding="utf-8")
    info = UpdateInfo(
        current_version="1.0.0",
        latest_version="2.0.0",
        manifest={
            "asset_filename": "app.zip",
            "download_url": ASSET_URL,
            "sha256": "abc",
            "signing_thumbprint": SIGNING_THUMBPRINT,
        },
        release={},
    )

    def fake_download(_url, dest, progress_cb=None):
        Path(dest).write_bytes(b"zip")
        assert progress_cb is not None
        assert progress_cb(50, 100) is True
        assert progress_cb(100, 100) is True

    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_make_update_temp_root", lambda _: str(temp_root))
    monkeypatch.setattr(updater, "download_file", fake_download)
    monkeypatch.setattr(updater, "compute_sha256", lambda path: "abc")
    monkeypatch.setattr(updater, "extract_zip", lambda zip_path, dest_dir: None)
    monkeypatch.setattr(updater, "verify_authenticode", lambda exe, thumbs: None)
    monkeypatch.setattr(updater, "launch_update_helper", lambda *args, **kwargs: (True, ""))
    progress = []

    ok, msg = download_and_apply_update(
        info,
        str(install),
        progress_cb=lambda phase, fraction: progress.append((phase, fraction)) or True,
    )

    assert ok, msg
    assert ("Downloading update...", 0.0) in progress
    assert ("Downloading update...", 0.35) in progress
    assert ("Downloading update...", 0.7) in progress
    assert ("Preparing restart...", 0.98) in progress


def test_update_helper_verifies_new_app_before_cleanup_and_retention():
    helper = Path("update_helper.bat").read_text(encoding="utf-8")

    launch = helper.index("Launching updated app and verifying startup")
    verify = helper.index("call :launch_and_verify_app", launch)
    cleanup = helper.index("Cleaning up staging folder", verify)
    retention = helper.index("Backup retention policy", cleanup)

    assert launch < verify < cleanup < retention


def test_update_helper_rolls_back_from_a_clean_runtime_surface():
    helper = Path("update_helper.bat").read_text(encoding="utf-8")

    rollback = helper.index("\n:rollback\n")
    clear_runtime = helper.index("call :clear_install_runtime", rollback)
    restore = helper.index('robocopy "%BACKUP_DIR%" "%INSTALL_DIR%"', clear_runtime)

    assert rollback < clear_runtime < restore
    assert "@('SerrebiTorrent_Data','config.json','.git','.venv','__pycache__')" in helper
    assert "Rollback did not restore" in helper


def test_update_helper_health_checks_the_restarted_executable():
    helper = Path("update_helper.bat").read_text(encoding="utf-8")

    section_start = helper.index("\n:launch_and_verify_app\n")
    section_end = helper.index("\n:launch_app_once\n", section_start)
    section = helper[section_start:section_end]

    assert "Start-Process" in section
    assert "-PassThru" in section
    assert "Start-Sleep -Seconds 3" in section
    assert "$p.HasExited" in section
    assert "exit 1" in section


def test_update_helper_only_clears_install_after_the_update_starts_applying():
    helper = Path("update_helper.bat").read_text(encoding="utf-8")

    # Earlier failures (app still running, files locked, backup failed) must not
    # wipe an install that was never fully backed up.
    first_rollback = helper.index("goto :rollback")
    applying = helper.index('set "UPDATE_APPLYING=1"')
    assert first_rollback < helper.index("Backing up current install") < applying
    rollback = helper[helper.index("\n:rollback\n"):helper.index("\n:launch_and_verify_app\n")]
    guard = rollback.index("if defined UPDATE_APPLYING (")
    assert guard < rollback.index("call :clear_install_runtime")
    assert 'set "RC=!ERRORLEVEL!"' in rollback


@patch('updater._download_manifest_url')
@patch('updater.fetch_latest_release')
def test_rate_limited_check_falls_back_to_latest_manifest(mock_fetch, mock_manifest):
    mock_fetch.side_effect = updater.RateLimitError("limited")
    mock_manifest.return_value = {
        "version": "99.99.99",
        "asset_filename": "app.zip",
        "download_url": "https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/download/v99.99.99/app.zip",
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }

    result = check_for_updates()

    assert result.status == "update_available"
    assert result.info.latest_version == "99.99.99"
    assert mock_manifest.call_args[0][0] == (
        "https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/latest/download/SerrebiTorrent-update.json"
    )


@patch('updater._download_manifest_url')
@patch('updater.fetch_latest_release')
def test_rate_limited_fallback_rejects_foreign_download_url(mock_fetch, mock_manifest):
    mock_fetch.side_effect = updater.RateLimitError("limited")
    mock_manifest.return_value = {
        "version": "99.99.99",
        "asset_filename": "app.zip",
        "download_url": "https://git.serrebiradio.com/someone/else/releases/download/v99.99.99/app.zip",
        "sha256": "a" * 64,
        "published_at": "2023-01-01",
        "signing_thumbprint": SIGNING_THUMBPRINT,
    }

    assert check_for_updates().status == "error"


@patch('updater._download_manifest_url')
@patch('updater.fetch_latest_release')
def test_rate_limited_status_kept_when_fallback_fails(mock_fetch, mock_manifest):
    mock_fetch.side_effect = updater.RateLimitError("limited")
    mock_manifest.side_effect = updater.UpdateError("offline")

    assert check_for_updates().status == "rate_limited"



def test_download_file_rejects_redirect_to_untrusted_host(tmp_path, monkeypatch):
    response = MagicMock()
    response.url = "https://evil.example/update.zip"
    response.status_code = 200
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    monkeypatch.setattr(updater.requests, "get", MagicMock(return_value=response))

    dest = tmp_path / "update.zip"

    with pytest.raises(UpdateError, match="HTTPS Forgejo release asset"):
        download_file(ASSET_URL, str(dest))

    assert not dest.exists()


def test_manifest_download_rejects_redirect_to_untrusted_host(monkeypatch):
    response = MagicMock()
    response.url = "https://evil.example/manifest.json"
    response.status_code = 200
    response.close = MagicMock()
    monkeypatch.setattr(updater.requests, "get", MagicMock(return_value=response))

    with pytest.raises(UpdateError, match="HTTPS Forgejo release asset"):
        updater._download_manifest_url(
            "https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/latest/download/SerrebiTorrent-update.json"
        )

    response.close.assert_called_once()



def test_download_redirect_is_validated_before_second_request(monkeypatch):
    first = MagicMock()
    first.status_code = 302
    first.headers = {"Location": "https://evil.example/update.zip"}
    first.close = MagicMock()

    calls = []
    def fake_get(url, **kwargs):
        calls.append(url)
        return first

    monkeypatch.setattr(updater.requests, "get", fake_get)

    with pytest.raises(UpdateError, match="HTTPS Forgejo release asset"):
        updater._get_validated_download_response(
            ASSET_URL,
            timeout=updater.DOWNLOAD_TIMEOUT,
            stream=True,
        )

    assert calls == [ASSET_URL]
    first.close.assert_called_once()


def test_download_redirect_count_is_bounded(monkeypatch):
    def fake_get(url, **kwargs):
        response = MagicMock()
        response.status_code = 302
        response.headers = {"Location": url}
        response.close = MagicMock()
        return response

    monkeypatch.setattr(updater.requests, "get", fake_get)
    monkeypatch.setattr(updater, "MAX_UPDATE_REDIRECTS", 1)

    with pytest.raises(UpdateError, match="redirected too many times"):
        updater._get_validated_download_response(
            ASSET_URL,
            timeout=updater.DOWNLOAD_TIMEOUT,
            stream=True,
        )



def test_fetch_latest_release_rejects_stream_over_limit(monkeypatch):
    class FakeResponse:
        status_code = 200
        reason = "OK"
        headers = {}

        def iter_content(self, chunk_size):
            yield b"123"
            yield b"45"

        def close(self):
            pass

    monkeypatch.setattr(updater, "MAX_UPDATE_RELEASE_BYTES", 4)
    monkeypatch.setattr(updater.requests, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(UpdateError, match="release metadata is larger"):
        updater.fetch_latest_release()


def test_fetch_latest_release_rejects_non_object_json(monkeypatch):
    response = _FakeResponse(
        status_code=200,
        chunks=[b"[]"],
        headers={"Content-Length": "2"},
    )
    monkeypatch.setattr(updater.requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(updater.UpdateError, match="JSON object"):
        updater.fetch_latest_release()


def test_download_manifest_rejects_non_object_json(monkeypatch):
    response = _FakeResponse(
        status_code=200,
        chunks=[b"[]"],
        headers={"Content-Length": "2"},
        url="https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/download/v1.2.3/update-manifest.json",
    )
    monkeypatch.setattr(updater, "_get_validated_download_response", lambda *args, **kwargs: response)
    monkeypatch.setattr(updater, "_validate_download_response_url", lambda _response: None)

    with pytest.raises(updater.UpdateError, match="JSON object"):
        updater._download_manifest_url(
            "https://git.serrebiradio.com/serrebi/SerrebiTorrent/releases/latest/download/update-manifest.json"
        )


def test_verify_authenticode_rejects_non_object_json(monkeypatch):
    result = SimpleNamespace(returncode=0, stdout="[]", stderr="")
    monkeypatch.setattr(updater, "_powershell_executables", lambda: ("powershell.exe",))
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: result)

    with pytest.raises(updater.UpdateError, match="invalid Authenticode data shape"):
        updater.verify_authenticode("SerrebiTorrent.exe", [SIGNING_THUMBPRINT])
