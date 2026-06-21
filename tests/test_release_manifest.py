import json

import pytest

from tools import release_manifest


def _manifest_inputs(tmp_path):
    zip_path = tmp_path / "SerrebiTorrent.zip"
    zip_path.write_bytes(b"release asset")
    notes_path = tmp_path / "release_notes.txt"
    notes_path.write_text("Release notes", encoding="utf-8")
    return {
        "version": "1.2.3",
        "asset_name": "SerrebiTorrent-v1.2.3.zip",
        "download_url": "https://example.test/SerrebiTorrent-v1.2.3.zip",
        "zip_path": zip_path,
        "notes_path": notes_path,
        "signtool_path": tmp_path / "signtool.exe",
        "exe_path": tmp_path / "SerrebiTorrent.exe",
    }


def test_build_manifest_requires_signing_thumbprint(tmp_path, monkeypatch):
    output_path = tmp_path / "manifest.json"
    monkeypatch.setattr(release_manifest, "_parse_signtool_thumbprint", lambda *_: None)

    with pytest.raises(RuntimeError, match="signing thumbprint"):
        release_manifest.build_manifest(
            **_manifest_inputs(tmp_path),
            signing_thumbprint=None,
            output_path=output_path,
        )

    assert not output_path.exists()


def test_build_manifest_normalizes_explicit_signing_thumbprint(tmp_path):
    output_path = tmp_path / "manifest.json"

    release_manifest.build_manifest(
        **_manifest_inputs(tmp_path),
        signing_thumbprint="aa " * 20,
        output_path=output_path,
    )

    manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert manifest["signing_thumbprint"] == "AA" * 20
