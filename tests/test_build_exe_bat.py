from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_checks_untracked_packageable_paths():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

    assert "call :ensure_packageable_untracked_clean || goto :error" in script
    assert "git ls-files --others --exclude-standard" in script
    assert "Untracked files under packageable paths can affect the release" in script
    assert "web_static/" in script
    assert "hooks/" in script
    assert "SerrebiTorrent.spec" in script
    assert "update_helper.bat" in script
    assert '".py"' in script
    assert '".dll"' in script
    assert '".pyd"' in script


def test_release_verifies_github_latest_endpoint():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

    assert "call :verify_latest_release || exit /b 1" in script
    assert 'gh api "repos/%GITHUB_OWNER%/%GITHUB_REPO%/releases/latest" --jq ".tag_name"' in script
    assert "The updater will keep reporting the old release until this is corrected." in script
