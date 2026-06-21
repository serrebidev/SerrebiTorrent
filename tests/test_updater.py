
import pytest
import sys
import os
import zipfile
from unittest.mock import MagicMock, patch

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
    get_allowed_thumbprints,
    verify_authenticode,
    APP_VERSION
)

ASSET_URL = "https://github.com/serrebidev/SerrebiTorrent/releases/download/v1.0.0/app.zip"
SIGNING_THUMBPRINT = "A" * 40


def release_with_asset(tag="v1.0.0", url=ASSET_URL):
    return {
        "tag_name": tag,
        "assets": [
            {
                "name": "app.zip",
                "browser_download_url": url,
            }
        ],
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
        "download_url": "https://github.com/serrebidev/SerrebiTorrent/releases/download/v1.0.1/app.zip",
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


def test_validate_manifest_rejects_non_github_download_url():
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
        "download_url": "https://github.com/serrebidev/SerrebiTorrent/releases/download/v1.0.0/other.zip",
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
                "browser_download_url": "https://github.com/serrebidev/SerrebiTorrent/releases/download/v1.0.0/SerrebiTorrent-update.json",
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
    url = "https://github.com/serrebidev/SerrebiTorrent/releases/download/v99.99.99/app.zip"
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
    url = "https://github.com/serrebidev/SerrebiTorrent/releases/download/v99.99.99/app.zip"
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


def test_launch_update_helper_is_hidden_and_uses_helper_cwd(monkeypatch, tmp_path):
    helper = tmp_path / "update_helper.bat"
    helper.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setenv("COMSPEC", "cmd.exe")
    popen = MagicMock()
    monkeypatch.setattr(updater.subprocess, "Popen", popen)

    ok, msg = launch_update_helper(str(helper), 1234, r"C:\Install", r"C:\Stage", temp_root=r"C:\Temp\SerrebiTorrent_update_x")

    assert ok, msg
    args, kwargs = popen.call_args
    assert args[0][:3] == ["cmd.exe", "/d", "/c"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["stdin"] is updater.subprocess.DEVNULL
    assert kwargs["stdout"] is updater.subprocess.DEVNULL
    assert kwargs["stderr"] is updater.subprocess.DEVNULL


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
    monkeypatch.setattr(updater, "download_file", lambda url, dest: open(dest, "wb").write(b"zip"))
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
