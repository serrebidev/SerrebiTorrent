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


def test_dry_run_fetches_tags_like_release():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

    dry_run_block = script[script.index('if /I "%MODE%"=="dry-run" (') :]
    assert "git fetch --tags" in dry_run_block


def test_release_uses_requested_signing_thumbprint_for_signtool():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

    assert "set \"SIGNTOOL_CERT_ARGS=/sha1 %SIGN_CERT_THUMBPRINT%\"" in script
    assert "%SIGNTOOL_CERT_ARGS% \".\\%EXE_NAME%\"" in script


def test_latest_zip_failure_stops_build():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

    latest_zip = "Compress-Archive -Path 'dist\\%APP_NAME%' -DestinationPath 'dist\\%APP_NAME%.zip' -Force"
    assert latest_zip in script
    assert script.index(latest_zip) < script.index("if errorlevel 1 goto :error", script.index(latest_zip))


def test_failed_release_create_cleans_drafts():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

    failure_block = script[script.index("if errorlevel 1 (\n    echo GitHub release creation failed.") :]
    assert "call :delete_draft_releases" in failure_block.split(")", 1)[0]
