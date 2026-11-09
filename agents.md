# SerrebiTorrent - agent notes

## Repo facts
- Location: Assume Windows 11, 64-bit.
- Entry point: `main.py`. GUI built with wxPython.
- Background libtorrent session lives in `session_manager.py`. Do not duplicate sessions.
- Indexer search lives in `torrent_search.py` (network, no wx) and `search_dialog.py` (wx, no network). Ported from blindDL; keep the two in step when either changes. `torrent_search.resolve()` returns `("magnet", str)` or `("file", bytes)` and is the only thing that fetches a private tracker's `.torrent`, so it must stay off the GUI thread.
- Never commit an indexer URL or API key. `DEFAULT_PREFERENCES` ships `torznab_feeds: []` / `disabled_torrent_sources: []`, and there are tests asserting that. `import_blinddl_feeds()` reads blindDL's config on the local machine only, adds names that are not configured here already, and never overwrites — the search dialog calls it on every open.
- Pull requests arrive from the `CIATA-BR` fork. The maintainer has push access to it, so fix a PR on its own branch (`git push https://github.com/CIATA-BR/SerrebiTorrent.git <local>:<branch>`) or merge and fix forward on `main`. Before merging, check the head keeps the whole tree (`git ls-tree -r --name-only <head> | wc -l`): #35 once carried a commit holding only the two files it touched, and merging it deleted everything else on `main`. GitHub is currently suspended, so the fork-PR flow is paused: `origin` is dead and `forgejo` is the live remote. When contributions resume they go to the Forgejo repo as Forgejo PRs.
- Locale codes come from each PO file's `Language` header, not from its filename: generated assets are `web_static/locales/<header>.json` plus `index.json`, and `tools/audit_bundle.py` requires exactly one `locales/<code>.po` and one matching Web catalog for every language in the packaged index. Filename/header drift passes `translation_tool.py check` but fails the release audit.
- Coverage counts any non-empty `msgstr` as translated, so it cannot catch machine-translated junk; read a catalog before trusting it. Messages built with values in the Web UI go through `TEMPLATES` in `web_static/i18n.js` (regex plus a `{placeholder}` key that is also a `PT_BR` key, so the extractor exports it); announce separate sentences in separate `announceToSR` calls so each is translated, and `announceToSR` queues calls made in the same tick. wx file-dialog wildcards (`Label|*.ext`) must keep everything after the first `|`; `validate_translation` enforces it.

## Runtime requirements
- Python 3.14 (64-bit).
- Core packages: see `requirements.txt`. Libs already installed in the user site-packages.
- Libtorrent DLL resolution happens in `libtorrent_env.py`. Always call `prepare_libtorrent_dlls()` before importing `libtorrent`.
- Release builds install the maintained libtorrent wheel into a clean build venv. Its hashed, vendored native dependencies are authoritative; do not explicitly add the repo-root OpenSSL or legacy 1.1 DLLs to frozen packages.

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
- Windows: run `build_exe.bat build` locally on this machine. Only the macOS `ci.yml` job below still uses a cloud runner.
- Linux: run `powershell -File tools\\build_linux_remote.ps1 -Version X.Y.Z`; it must build through SSH on `root@serrebiradio.com`.
- macOS: `.github/workflows/ci.yml` still builds natively on GitHub's macOS runner when the tag is pushed there, and attaches the zip to the Forgejo release (needs a `FORGEJO_TOKEN` repo secret on GitHub). Releases work without it.
- The `.spec` file uses PyInstaller's import analysis rather than collecting every dependency submodule. It explicitly requires the libtorrent extension so PyInstaller follows only its referenced native dependencies.
- Every package runs `tools/audit_bundle.py` and `tools/verify_frozen.py` before it is accepted.
- `icon.ico` is conditionally included in the build only if it exists in the root directory.
- Release: run `build_exe.bat release` from a clean tree with `SIGN_CERT_THUMBPRINT=FB99DDCECA07B170E0A950F0C780AD899D28D770` and `FORGEJO_TOKEN` (Forgejo API token, stored at `/root/forgejo-muse-token.txt` on the VPS) exported, so the manifest keeps `signing_thumbprint` and the updater keeps trusting the build. It pushes branch + tag to the `forgejo` remote and publishes via `tools/forgejo_release.py` (draft → upload → publish → sweep drafts → verify `/releases/latest`).
- A release that dies after the version bump leaves `app_version.py` modified, and every retry then aborts with "Working tree has uncommitted tracked changes" — run `git checkout -- app_version.py` and retry. The same guard fires when `app_version.py` is already ahead of the newest tag: `release_tools.ps1` finds no tag to diff against, falls back to the full history, and publishes release notes for every commit ever made.
- The cloud release pipeline (`.github/workflows/cloud-release.yml`) was removed in the Forgejo move: releases publish from this host, and only the macOS `ci.yml` job still uses GitHub runners. `build_exe.bat release` still accepts a prebuilt Linux tarball via `SERREBITORRENT_LINUX_TARBALL`.
- `libtorrent-wheels` is a pre-release holding the maintained CPython 3.14 wheels (Windows from `%USERPROFILE%\libtorrent-build\wheels`, Linux from `/root/libtorrent-build/wheels` on the VPS). It is never Latest and not a `v*` tag, so the updater and version logic ignore it. It lives on GitHub, so it is unreachable while the account is suspended; host releases use the local wheel dir. The refresh flow (`gh release upload`, `LIBTORRENT_WHEEL_SUMS_SHA256` pin) died with `cloud-release.yml`; while GitHub is suspended there is no wheels store to refresh.
- Pushing a tag to GitHub runs `ci.yml`, which builds the macOS app and attaches `SerrebiTorrent-vX.Y.Z-macos-ARM64.zip` to the Forgejo release, retrying until the release exists. That job also runs the suite — run `python -m pytest` locally before tagging anyway. The other `.github/workflows` jobs only verify and publish nothing.

## Packaging
- Ship the entire `SerrebiTorrent` folder from the `dist` directory. The main executable is `SerrebiTorrent.exe` inside that folder.
- User data (profiles, preferences, resume data, logs) lives under `SerrebiTorrent_Data` next to the EXE (or the distribution folder) in portable mode.
- To preconfigure profiles for distribution, ship a `SerrebiTorrent_Data\config.json` (use `config.example.json` as a starting point).
- If you rebrand the EXE, update the `.spec` file and any doc references. Remember to refresh the tray icon (`icon.ico`) if you change branding.

## Ops notes
- Source mode may need native DLL directories in `PATH`; `libtorrent_env.py` prepares them before libtorrent is imported. Don't delete that helper.
- Connection profiles, preferences, session state, and logs write to `SerrebiTorrent_Data` (portable mode) or per-user app data (installed mode).
- Accessibility shortcuts are hard-coded in `MainFrame.__init__`. Update README if you touch them.
- Run `python -m pytest` for the suite under `tests/`. It does not cover the UI end to end, so also launch `python main.py` and exercise anything you touched.

## Update notes
- The reported qBittorrent version is no longer a release chore: `qbittorrent_version()` in `session_manager.py` looks it up from qBittorrent's GitHub releases once a day and caches it in the state dir. `QBITTORRENT_FALLBACK_VERSION` is only used offline or when the lookup fails — bump it occasionally, but nothing breaks if you forget.
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
- Release builds must publish the Forgejo release as non-draft/latest and remove any remaining draft releases. Never leave draft releases behind.

## Known build issues
- PyInstaller 6.x prints an elevated-shell deprecation warning when the build is launched from an administrator terminal. The build succeeds; run the release command from a non-admin terminal to avoid the warning.
- The current Authenticode certificate is self-signed, so `signtool verify /pa` reports an untrusted root on a stock machine even though the EXE is signed and timestamped. The updater accepts its manifest thumbprint; eliminating the initial Windows trust prompt requires a publicly trusted code-signing certificate.

Keep edits lean, comment only when code is not self-explanatory, and leave user-facing docs in README.md. Everything technical goes here.

## Agent skills

### Issue tracker

Issues are tracked in this repo's Forgejo issues, via the Forgejo API with `FORGEJO_TOKEN`. See `docs/agents/issue-tracker.md`. (The old GitHub issues are unreachable while that account is suspended.)

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
