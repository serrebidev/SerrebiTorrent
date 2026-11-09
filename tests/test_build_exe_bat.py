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


def test_release_verifies_forgejo_latest_endpoint():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")
    release = (ROOT / "tools" / "forgejo_release.py").read_text(encoding="utf-8")

    assert "call :forgejo_release || goto :error" in script
    assert "tools\\forgejo_release.py" in script
    assert '--host "%FORGEJO_HOST%" --repo "%FORGEJO_REPO%"' in script
    assert "/releases/latest" in release
    assert "The updater will keep reporting the old release until this is corrected." in release


def test_dry_run_fetches_tags_like_release():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

    dry_run_block = script[script.index('if /I "%MODE%"=="dry-run" (') :]
    assert "git fetch --tags forgejo" in dry_run_block


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
    release = (ROOT / "tools" / "forgejo_release.py").read_text(encoding="utf-8")

    failure_block = script[script.index("if errorlevel 1 (\n    echo Forgejo release creation failed.") :]
    assert "exit /b 1" in failure_block.split(")", 1)[0]
    assert "sweep_drafts(client)" in release
    assert "Cleaning up draft release" in release


def test_build_verifies_the_frozen_runtime_before_signing():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

    verify = 'tools\\verify_frozen.py "dist\\%APP_NAME%\\%EXE_NAME%"'
    assert verify in script
    assert script.index(verify) < script.index("Signing %EXE_NAME%")


def test_build_uses_isolated_maintained_libtorrent_wheel():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

    assert 'set "BUILD_VENV=%ROOT%build\\venv"' in script
    assert "tools\\select_libtorrent_wheel.py" in script
    assert 'set "LIBTORRENT_WHEEL_DIR=%USERPROFILE%\\libtorrent-build\\wheels"' in script
    assert '--force-reinstall --no-deps "%LIBTORRENT_WHEEL%"' in script
    assert '--expected-libtorrent "!LIBTORRENT_VERSION!"' in script


def test_release_builds_linux_over_ssh_and_uploads_it():
    script = (ROOT / "build_exe.bat").read_text(encoding="utf-8")

    assert "tools\\build_linux_remote.ps1" in script
    assert '"dist\\%APP_NAME%-v%NEXT_VERSION%-linux-x86_64.tar.gz"' in script
