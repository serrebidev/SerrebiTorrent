from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "update_helper.bat"
MAIN = ROOT / "main.py"


def _helper_text() -> str:
    return HELPER.read_text(encoding="utf-8")


def test_update_helper_stops_and_checks_install_before_file_moves():
    text = _helper_text()

    stop_call = text.index("call :ensure_app_stopped")
    unlock_call = text.index("call :verify_install_unlocked")
    backup_move = text.index('robocopy "%INSTALL_DIR%" "%BACKUP_DIR%"')

    assert stop_call < unlock_call < backup_move
    assert "CloseMainWindow" in text
    assert "Stop-Process -Id $p.Id -Force" in text
    assert "SerrebiTorrent is still running from the install folder" in text


def test_update_helper_verifies_install_drained_before_apply():
    text = _helper_text()

    backup_move = text.index('robocopy "%INSTALL_DIR%" "%BACKUP_DIR%"')
    drained_call = text.index("call :verify_install_drained")
    apply_move = text.index('robocopy "%STAGING_DIR%" "%INSTALL_DIR%"')

    assert backup_move < drained_call < apply_move
    assert ":verify_install_drained" in text
    assert "Files remained in the install folder after backup" in text


def test_update_helper_preserves_serrebitorrent_user_data():
    text = _helper_text()

    assert "/XD SerrebiTorrent_Data" in text
    assert "/XF config.json" in text
    assert "SERREBITORRENT_KEEP_BACKUPS" in text


def test_update_helper_relocated_batch_shell_exits_cleanly():
    text = _helper_text()

    assert 'start "" /b cmd /d /c call "!TMP_HELPER!"' in text
    assert 'start "" /b "!TMP_HELPER!"' not in text


def test_update_helper_accepts_and_cleans_temp_root():
    text = _helper_text()

    assert 'set "TEMP_ROOT=%ARG5%"' in text
    assert "call :schedule_temp_cleanup" in text
    assert "_SerrebiTorrent_update_tmp" in text


def test_startup_cleans_leftover_update_artifacts():
    text = MAIN.read_text(encoding="utf-8")

    assert "updater.cleanup_update_artifacts()" in text


def test_temp_cleanup_binds_paths_via_env_not_broken_param():
    text = _helper_text()

    # A PowerShell param() block under -Command does NOT bind trailing
    # arguments (only -File or &{...} do), so the generated temp-cleanup
    # script must pass the paths through environment variables instead.
    assert 'set "CLEAN_TEMP_ROOT=%TEMP_ROOT_TO_DELETE%"' in text
    assert 'set "CLEAN_INSTALL_DIR=%INSTALL_DIR%"' in text
    assert "$env:CLEAN_TEMP_ROOT" in text
    assert "$env:CLEAN_INSTALL_DIR" in text


def test_no_broken_param_binding_under_command():
    text = _helper_text()

    # Guard against reintroducing the param()-under--Command anti-pattern,
    # which silently leaves the parameters empty.
    assert "param([string]$path" not in text
    assert "param([string]$log)" not in text
    assert "$log=[string]$env:LOG_FILE" in text
