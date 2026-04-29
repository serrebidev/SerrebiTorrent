# SerrebiTorrent – agent notes

## Repo facts
- Location: Assume Windows 11, 64‑bit.
- Entry point: `main.py`. GUI built with wxPython.
- Background libtorrent session lives in `session_manager.py`. Do not duplicate sessions.


## Runtime requirements
- Python 3.14 (64‑bit).
- Core packages: see `requirements.txt`. Libs already installed in the user site-packages.
- Libtorrent DLL resolution happens in `libtorrent_env.py`. Always call `prepare_libtorrent_dlls()` before importing `libtorrent`.
- OpenSSL 3 DLLs (`libcrypto-3-x64.dll`, `libssl-3-x64.dll`) sit in the repo root and are bundled into the EXE (required for libtorrent HTTPS). Legacy 1.1 DLLs remain for compatibility.

## Threading Model
- **Blocking I/O:** All network operations (fetching torrents, sending commands like start/stop/remove) MUST be offloaded to a background thread to prevent freezing the GUI.
- **Implementation:** `MainFrame` uses a `concurrent.futures.ThreadPoolExecutor`.
- **Pattern:**
    1. UI event triggers a method (e.g., `on_remove`).
    2. Method submits a worker function (e.g., `_remove_background`) to `self.thread_pool`.
    3. Worker function performs blocking calls.
    4. Worker uses `wx.CallAfter` to invoke a UI-thread method (e.g., `_on_action_complete`) to update the display/statusbar.
    5. **Never** call `self.client` methods directly from the main GUI thread.

## Build commands
- Install deps (only if new environment): `python -m pip install -r requirements.txt`.
- Build EXE: `pyinstaller SerrebiTorrent.spec`. Output lands in `dist\\SerrebiTorrent\\`.
- The `.spec` file is configured for a directory-based distribution (`onedir`) to improve stability and startup performance. It includes all submodules for major dependencies (`flask`, `requests`, `qbittorrentapi`, `transmission_rpc`, `bs4`, `yaml`, etc.) using `collect_submodules`.
- It also bundles the web UI (`web_static`), OpenSSL DLLs, and other resources into the distribution folder.
- Hidden imports explicitly include local modules (`clients`, `rss_manager`, `web_server`, etc.) and core dependency sub-components (`werkzeug`, `jinja2`, `urllib3`) to ensure compatibility across different environments.
- `icon.ico` is conditionally included in the build only if it exists in the root directory.
- OpenSSL 3 DLLs are explicitly added (`libssl-3-x64.dll`, `libcrypto-3-x64.dll`); keep them in the repo root before building. Legacy 1.1 DLLs are still bundled for compatibility.

## Packaging
- Ship the entire `SerrebiTorrent` folder from the `dist` directory. The main executable is `SerrebiTorrent.exe` inside that folder.
- User data (profiles, preferences, resume data, logs) lives under `SerrebiTorrent_Data` next to the EXE (or the distribution folder) in portable mode.
- To preconfigure profiles for distribution, ship a `SerrebiTorrent_Data\config.json` (use `config.example.json` as a starting point).
- If you rebrand the EXE, update the `.spec` file and any doc references. Remember to refresh the tray icon (`icon.ico`) if you change branding.

## Ops notes
- Local mode needs the OpenSSL DLLs in `PATH`; `libtorrent_env.py` already injects both the repo root and Python's `DLLs` directory. Don't delete that helper.
- Connection profiles, preferences, session state, and logs write to `SerrebiTorrent_Data` (portable mode) or per-user app data (installed mode).
- Accessibility shortcuts are hard-coded in `MainFrame.__init__`. Update README if you touch them.
- If you must run tests, there are no automated suites. Launch `python main.py` and exercise the UI manually.

## Update notes
- The updater accepts a `signing_thumbprint` value in the release manifest so self-signed Authenticode signatures can be trusted when Windows reports UnknownError.
- Release manifests are generated via `tools/release_manifest.py`, which parses `signtool verify` output to capture the signing thumbprint (override with `SIGN_CERT_THUMBPRINT`).
- Version bumps in `build_exe.bat` now call `tools/update_version.py` to update `app_version.py` safely (avoids PowerShell quoting pitfalls).
- Update process runs completely hidden (no CMD windows) via `STARTUPINFO` with `SW_HIDE` flag.
- Backups are cleaned up automatically: default keeps 1 backup with 5-minute grace period; configure via `SERREBITORRENT_KEEP_BACKUPS` env var.
- Staging folders (`<AppName>_Update_<timestamp>`) are deleted immediately after successful update, or by a short detached cleanup when the helper is running from the staging folder itself.
- Test updater end-to-end with `python tools\test_updater_e2e.py` or manually with `python tools\test_updater_manual.py`.

## Build hygiene
- After building (`pyinstaller SerrebiTorrent.spec`), check the output for any warnings, errors, or bugs.
- Always fix any warnings, bugs, or errors encountered during the build if you can. Do not leave known issues unresolved.
- If a fix is not possible (e.g., upstream bug, missing context), document the issue here under "Known build issues" so it is tracked.

## Known build issues
- PyInstaller 6.x prints an elevated-shell deprecation warning when the build is launched from an administrator terminal. The build succeeds; run the release command from a non-admin terminal to avoid the warning.

Keep edits lean, comment only when code is not self-explanatory, and leave user-facing docs in README.md. Everything technical goes here.
