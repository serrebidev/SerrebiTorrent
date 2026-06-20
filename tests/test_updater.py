
import pytest
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from updater import (
    parse_semver,
    format_version,
    is_newer_version,
    _is_sha256,
    validate_manifest,
    UpdateError,
    UpdateInfo,
    check_for_update,
    get_allowed_thumbprints,
    verify_authenticode,
    APP_VERSION
)

ASSET_URL = "https://github.com/serrebidev/SerrebiTorrent/releases/download/v1.0.0/app.zip"


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
        "published_at": "2023-01-01"
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
        "published_at": "2023-01-01"
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
        "published_at": "2023-01-01"
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
        "published_at": "2023-01-01"
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
        "published_at": "2023-01-01"
    }
    
    # We rely on APP_VERSION being importable and smaller than 99.99.99
    update_info = check_for_update()
    assert update_info is not None
    assert update_info.latest_version == "99.99.99"

@patch('updater.fetch_latest_release')
def test_check_for_update_none(mock_fetch):
    mock_fetch.return_value = release_with_asset(tag="v0.0.0") # Very old
    update_info = check_for_update()
    assert update_info is None
