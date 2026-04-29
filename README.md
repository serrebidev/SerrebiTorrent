# SerrebiTorrent

SerrebiTorrent is a Windows desktop torrent manager designed for keyboard-first use and screen readers. It can manage torrents on this PC (local libtorrent) or control a remote client (qBittorrent, Transmission, rTorrent).

**Latest:** v1.5.43 - Refreshed bundled libtorrent build

## What you get
- Connect to local libtorrent, rTorrent (SCGI/XML-RPC), qBittorrent, or Transmission from one interface.
- Live download/upload speeds, progress, ratio, tracker host, and status messages for each torrent.
- Create torrents.
- Responsive UI: remote operations run in the background to avoid freezing.
- Quick filters (All, Downloading, Complete, Active) plus a tracker tree in the sidebar.
- Keyboard workflow + tray support that plays nicely with NVDA and other screen readers.

## Download & run (portable)
1. Download the latest ZIP from https://github.com/serrebidev/SerrebiTorrent/releases
2. Extract the entire `SerrebiTorrent` folder somewhere (example: `C:\Portable\SerrebiTorrent\`).
3. Run `SerrebiTorrent.exe` (do not move the EXE out of its folder).

Portable data (profiles, preferences, resume data, logs) lives next to the app in `SerrebiTorrent_Data\`.

## First-time setup
- Open Connection Manager: `Ctrl+Shift+C` (or tray icon → Switch Profile → Connection Manager...)
- Add a profile and connect:
  - **Local**: manages torrents via libtorrent on this PC (default profile on first run).
  - **Remote**: point at qBittorrent / Transmission / rTorrent and enter credentials if needed.

## Settings
- Local session + app settings: Tools → Local Session Settings… (Ctrl+,) (or tray icon → Settings → Local Session Settings…)
- Remote client settings (enabled only when connected): Tools → qBittorrent/Transmission/rTorrent Remote Settings… (or tray icon → Settings → …)

## Auto-updater (Windows)
The app checks GitHub Releases for updates. You can enable/disable the startup check in Local Session Settings, or run Tools → Check for Updates.

Update flow:
- Downloads the release ZIP from GitHub using the update manifest asset (`SerrebiTorrent-update.json`).
- Verifies the ZIP SHA-256 from the manifest.
- Verifies Authenticode signature on the new `SerrebiTorrent.exe`.
- Uses a helper script to swap folders safely, keep a backup, and restart the app.

If an update fails, check the updater log in `%TEMP%\SerrebiTorrent_update_*.log`.

## Release pipeline (automated)
Prereqs:
- Python 3.14 + dependencies from `requirements.txt`
- Git + GitHub CLI (`gh auth login` completed)
- Code signing cert installed
- SignTool available (default path used, or set `SIGNTOOL_PATH`)

Commands:
- `build_exe.bat build` builds, signs, and zips locally.
- `build_exe.bat release` auto-bumps version, builds, signs, zips, tags, pushes, creates the GitHub release, and uploads the update manifest.
- `build_exe.bat dry-run` shows what it would do without modifying anything.

Versioning uses the latest `vMAJOR.MINOR.PATCH` tag as the base. If none exists, it starts at `v1.0.0`. Commits with `BREAKING CHANGE` or `!:` bump major; commits starting with `feat` (or containing `feature`) bump minor; otherwise it bumps patch.

## Build from source (developers)
Commands:
- `git clone https://github.com/serrebidev/SerrebiTorrent`
- `python -m pip install -r requirements.txt`
- `build_exe.bat build`

Build output lands in `dist\SerrebiTorrent\`. For distribution, zip the entire `SerrebiTorrent` folder (not just the EXE).

## Accessibility & shortcuts
Everything stays reachable by keyboard:
- Ctrl+Shift+C: Connection Manager
- Ctrl+O / Ctrl+U: Add torrent file / Add URL or magnet
- Ctrl+S / Ctrl+P: Start / Stop selected torrents
- Delete / Shift+Delete: Remove / Remove with data
- Ctrl+A: Select all
- Tab: Toggle focus between the sidebar and torrent list; double-clicking the tray icon restores the window.
- Ctrl+N: Create a torrent

Need to troubleshoot? Logs live under `SerrebiTorrent_Data\logs` next to the EXE/script in portable mode (or per-user app data in installed mode). Open `AGENTS.md` if you need technical or build details.

## Auto-update

SerrebiTorrent includes automatic update functionality:

### Update Process
1. App checks GitHub releases for newer versions (manual via Tools menu or automatic on startup if enabled)
2. Downloads update ZIP and verifies SHA-256 checksum and Authenticode signature
3. Launches hidden helper script that:
   - Waits for app to exit
   - Backs up current installation to `<install_dir>_backup_<timestamp>`
   - Applies update by moving new files to install directory
   - Restarts the app
4. Backup cleanup runs automatically:
   - **Default:** Keeps 1 backup (newest) and deletes it after 5-minute grace period
   - **Immediate:** Set `SERREBITORRENT_KEEP_BACKUPS=0` to delete backup immediately after successful update
   - **Multiple:** Set `SERREBITORRENT_KEEP_BACKUPS=N` to keep N most recent backups

### Configuration
- **Backup Retention:** Set environment variable `SERREBITORRENT_KEEP_BACKUPS` to control how many backup folders to keep (default: 1)
- **Signing Trust:** Set `SERREBITORRENT_TRUSTED_SIGNING_THUMBPRINTS` to comma-separated list of trusted certificate thumbprints

### Notes
- The update process runs completely hidden (no CMD windows appear)
- User data in `SerrebiTorrent_Data` is preserved during updates
- If an update fails, the backup is automatically restored
- Backups are cleaned up automatically after a grace period to allow manual rollback if needed

## Test plan (manual)
- Build a release with `build_exe.bat release` and extract the ZIP to a folder like `C:\Temp\SerrebiTorrent-old`.
- Create a newer release (make a small commit, then run `build_exe.bat release` again).
- Launch the older app, run Tools -> Check for Updates, accept the prompt, and confirm:
  - The app closes and restarts on the new version
  - No CMD/console windows appear during the update
  - After 5 minutes, backup folders are automatically cleaned up (or immediately if `SERREBITORRENT_KEEP_BACKUPS=0`)
  - The status bar reports update status or errors clearly
