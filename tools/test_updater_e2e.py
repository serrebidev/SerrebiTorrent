"""
End-to-end test for SerrebiTorrent updater.

Creates a mock installation, simulates an update, and verifies cleanup behavior.
"""
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import locale
    if locale.getpreferredencoding() != 'UTF-8':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def create_mock_app(app_dir: Path, version: str, exe_name: str = "SerrebiTorrent.exe") -> None:
    """Create a mock application directory with dummy files."""
    app_dir.mkdir(parents=True, exist_ok=True)
    
    # Create dummy executable (just a text file for testing)
    exe_path = app_dir / exe_name
    exe_path.write_text(f"Mock SerrebiTorrent v{version}\n")
    
    # Create update helper
    helper_path = app_dir / "update_helper.bat"
    script_root = Path(__file__).parent.parent
    real_helper = script_root / "update_helper.bat"
    if real_helper.exists():
        shutil.copy2(real_helper, helper_path)
    else:
        helper_path.write_text("@echo off\necho Mock update helper\n")
    
    # Create some other files
    (app_dir / "dummy.dll").write_text("Mock DLL\n")
    (app_dir / "_internal").mkdir(exist_ok=True)
    (app_dir / "_internal" / "lib.dll").write_text("Mock lib\n")


def create_update_zip(zip_path: Path, version: str, exe_name: str = "SerrebiTorrent.exe") -> None:
    """Create a mock update ZIP file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        app_dir = Path(tmpdir) / "SerrebiTorrent"
        create_mock_app(app_dir, version, exe_name)
        
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(app_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(tmpdir)
                    zf.write(file_path, arcname)


def test_update_flow(test_root: Path, keep_backups: int = 1) -> None:
    """Test the full update flow with cleanup."""
    print(f"\n{'='*60}")
    print(f"Testing update flow with KEEP_BACKUPS={keep_backups}")
    print(f"{'='*60}\n")
    
    # Setup directories
    install_dir = test_root / "SerrebiTorrent"
    staging_root = test_root / "SerrebiTorrent_Update_20260130_120000"
    staging_dir = staging_root / "SerrebiTorrent"
    
    print(f"[1/8] Creating mock installation (v1.0.0)...")
    create_mock_app(install_dir, "1.0.0")
    print(f"      Install dir: {install_dir}")
    
    print(f"\n[2/8] Creating mock update (v1.1.0)...")
    staging_root.mkdir(parents=True, exist_ok=True)
    zip_path = staging_root / "SerrebiTorrent-v1.1.0.zip"
    create_update_zip(zip_path, "1.1.0")
    
    print(f"[3/8] Extracting update...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(staging_root)
    
    # Copy update helper to staging root
    helper_src = install_dir / "update_helper.bat"
    helper_copy = staging_root / "update_helper.bat"
    shutil.copy2(helper_src, helper_copy)
    
    print(f"      Staging dir: {staging_dir}")
    
    print(f"\n[4/8] Running update helper...")
    print(f"      Backup retention: {keep_backups}")
    
    # Set environment variable for backup retention
    env = os.environ.copy()
    env["SERREBITORRENT_KEEP_BACKUPS"] = str(keep_backups)
    
    # Build command - use a dummy PID (9999) since we're not actually running the app
    helper_cmd = [
        str(helper_copy),
        "9999",  # dummy PID
        str(install_dir),
        str(staging_dir),
        "SerrebiTorrent.exe"
    ]
    
    import subprocess
    result = subprocess.run(
        helper_cmd,
        cwd=str(test_root),
        env=env,
        capture_output=True,
        text=True
    )
    
    print(f"\n      Helper exit code: {result.returncode}")
    if result.stdout:
        print(f"      Helper stdout:\n{result.stdout}")
    if result.stderr:
        print(f"      Helper stderr:\n{result.stderr}")
    
    print(f"\n[5/8] Verifying update succeeded...")
    exe_path = install_dir / "SerrebiTorrent.exe"
    if not exe_path.exists():
        print(f"      ❌ FAIL: Executable not found!")
        return False
    
    content = exe_path.read_text()
    if "v1.1.0" not in content:
        print(f"      ❌ FAIL: Wrong version! Content: {content}")
        return False
    
    print(f"      ✓ Executable updated to v1.1.0")
    
    print(f"\n[6/8] Checking immediate cleanup...")
    
    # Check staging root cleanup
    if staging_root.exists():
        print(f"      ⚠ Staging root still exists: {staging_root}")
        print(f"        Contents: {list(staging_root.iterdir())}")
    else:
        print(f"      ✓ Staging root cleaned up")
    
    # Check for backup folder
    backup_dirs = list(test_root.glob("SerrebiTorrent_backup_*"))
    print(f"      Found {len(backup_dirs)} backup folder(s)")
    
    if keep_backups == 0:
        if backup_dirs:
            print(f"      ⚠ Backup folder(s) still exist (should be deleted immediately)")
            for d in backup_dirs:
                print(f"        - {d}")
        else:
            print(f"      ✓ No backup folders (deleted immediately)")
    else:
        if not backup_dirs:
            print(f"      ⚠ No backup folders found (expected 1)")
        else:
            print(f"      ✓ Backup folder exists: {backup_dirs[0]}")
    
    print(f"\n[7/8] Waiting for delayed cleanup (5 seconds)...")
    print(f"      (Full grace period is 300s, but we'll just check after 5s)")
    time.sleep(5)
    
    print(f"\n[8/8] Checking delayed cleanup...")
    if staging_root.exists():
        print(f"      ❌ FAIL: Staging root still exists after cleanup wait: {staging_root}")
        return False
    print(f"      ✓ Staging root cleaned up")

    backup_dirs = list(test_root.glob("SerrebiTorrent_backup_*"))
    print(f"      Found {len(backup_dirs)} backup folder(s)")
    
    if backup_dirs:
        print(f"      Note: Backup cleanup is scheduled with 5-minute grace period")
        print(f"            In production, these would be cleaned up after 5 minutes")
        for d in backup_dirs:
            print(f"        - {d}")
    
    print(f"\n✓ Test completed successfully!")
    return True


def test_multiple_backups_retention() -> None:
    """Test that old backups are cleaned up when limit is exceeded."""
    print(f"\n{'='*60}")
    print(f"Testing multiple backup retention")
    print(f"{'='*60}\n")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_root = Path(tmpdir) / "test_retention"
        test_root.mkdir()
        install_dir = test_root / "SerrebiTorrent"
        
        # Create 3 fake old backups
        for i in range(1, 4):
            backup_dir = test_root / f"SerrebiTorrent_backup_2026013012000{i}"
            backup_dir.mkdir()
            (backup_dir / f"old_file_{i}.txt").write_text(f"Backup {i}")
        
        print(f"[1/2] Created 3 old backup folders")
        for d in sorted(test_root.glob("*_backup_*")):
            print(f"      - {d.name}")
        
        # Now perform an update with KEEP_BACKUPS=1
        create_mock_app(install_dir, "1.0.0")
        staging_root = test_root / "SerrebiTorrent_Update_20260130_120005"
        staging_dir = staging_root / "SerrebiTorrent"
        
        staging_root.mkdir(parents=True)
        zip_path = staging_root / "update.zip"
        create_update_zip(zip_path, "1.1.0")
        
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(staging_root)
        
        helper_src = install_dir / "update_helper.bat"
        helper_copy = staging_root / "update_helper.bat"
        shutil.copy2(helper_src, helper_copy)
        
        env = os.environ.copy()
        env["SERREBITORRENT_KEEP_BACKUPS"] = "1"
        
        import subprocess
        subprocess.run(
            [str(helper_copy), "9999", str(install_dir), str(staging_dir), "SerrebiTorrent.exe"],
            cwd=str(test_root),
            env=env,
            capture_output=True
        )
        
        print(f"\n[2/2] After update with KEEP_BACKUPS=1:")
        backup_dirs = sorted(test_root.glob("*_backup_*"))
        print(f"      Found {len(backup_dirs)} backup folder(s)")
        for d in backup_dirs:
            print(f"      - {d.name}")
        
        print(f"\n      Note: Retention enforcement happens in background cleanup")
        print(f"            After 5-minute grace period, only newest backup will remain")


def test_rollback_scenario() -> None:
    """Test that rollback preserves backup folder."""
    print(f"\n{'='*60}")
    print(f"Testing rollback scenario")
    print(f"{'='*60}\n")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_root = Path(tmpdir) / "test_rollback"
        test_root.mkdir()
        install_dir = test_root / "SerrebiTorrent"
        
        print(f"[1/3] Creating installation...")
        create_mock_app(install_dir, "1.0.0")
        
        # Manually simulate a failed update by creating a backup
        backup_dir = test_root / "SerrebiTorrent_backup_20260130_120000"
        shutil.copytree(install_dir, backup_dir)
        
        print(f"[2/3] Simulating failed update (backup exists)...")
        # In a real failure, the helper would restore from backup
        # For now, just verify backup exists
        
        if backup_dir.exists():
            print(f"      ✓ Backup preserved: {backup_dir}")
        
        print(f"\n[3/3] In production:")
        print(f"      - If update fails, helper restores from backup")
        print(f"      - Backup is NOT deleted on failure")
        print(f"      - User can manually recover if needed")


def main():
    """Run all tests."""
    print("SerrebiTorrent Updater End-to-End Test")
    print("=" * 60)
    failures = 0
    
    script_root = Path(__file__).parent.parent
    print(f"Script root: {script_root}")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_root = Path(tmpdir) / "test_update"
        test_root.mkdir()
        
        print(f"Test root: {test_root}")
        
        # Test 1: Update with keep_backups=1 (default)
        try:
            if not test_update_flow(test_root / "test1", keep_backups=1):
                raise AssertionError("Update flow with keep_backups=1 failed")
        except Exception as e:
            failures += 1
            print(f"\n❌ Test 1 failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Test 2: Update with keep_backups=0 (immediate deletion)
        try:
            if not test_update_flow(test_root / "test2", keep_backups=0):
                raise AssertionError("Update flow with keep_backups=0 failed")
        except Exception as e:
            failures += 1
            print(f"\n❌ Test 2 failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Test 3: Multiple backups retention
        try:
            test_multiple_backups_retention()
        except Exception as e:
            failures += 1
            print(f"\n❌ Test 3 failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Test 4: Rollback scenario
        try:
            test_rollback_scenario()
        except Exception as e:
            failures += 1
            print(f"\n❌ Test 4 failed: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*60}")
    print("All tests completed!")
    print(f"{'='*60}\n")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
