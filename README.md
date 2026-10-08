# SerrebiTorrent

**English** | [Português (Brasil)](README.pt-BR.md)

A vibe-coded, keyboard-first, screen-reader-friendly torrent manager for Windows. Manage torrents locally with built-in libtorrent, or drive a remote client — qBittorrent, Transmission, or rTorrent — from the same interface.

[![Join SerrebiProjects on Telegram](https://img.shields.io/badge/Telegram-SerrebiProjects-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/SerrebiProjects)

**Questions, bugs, or release news?** Join the [SerrebiProjects Telegram group](https://t.me/SerrebiProjects), the fastest place to get help.

## Features

- Connects to local libtorrent, or a remote qBittorrent, Transmission, or rTorrent (SCGI/XML-RPC) client, all from one interface.
- Live download/upload speeds, progress, ratio, tracker host, and status messages for each torrent.
- Searches torrent indexers and adds what you pick, without leaving the app.
- Creates torrents.
- Responsive UI: remote operations run in the background so the app never freezes.
- Quick filters (All, Downloading, Complete, Active) plus a tracker tree in the sidebar.
- Full keyboard workflow and tray support, built and tested with NVDA.
- Reorder torrent queues on qBittorrent, Transmission, and the built-in libtorrent client; unsupported backends report that explicitly.
- Built-in updater that verifies SHA-256 and Authenticode before applying an update, with automatic backup and rollback.

## Download and install

Grab the latest build from the [Releases page](https://github.com/serrebidev/SerrebiTorrent/releases). Latest: **v1.12.0**.

**Windows portable**

1. Download the latest ZIP.
2. Extract the entire `SerrebiTorrent` folder somewhere (example: `C:\Portable\SerrebiTorrent\`).
3. Run `SerrebiTorrent.exe` — don't move the EXE out of its folder.

The ZIP contains SerrebiTorrent's private Python runtime, libtorrent, OpenSSL,
web interface, and update helper. A regular Windows 11 64-bit computer does
not need Python, pip, Visual C++ build tools, or a separate torrent client.

Portable data (profiles, preferences, resume data, logs) lives next to the app in `SerrebiTorrent_Data\`. Updating in place keeps this data untouched.

**Linux x86-64**

1. Download the Linux `.tar.gz` package.
2. Extract it and run `SerrebiTorrent/SerrebiTorrent`.

The Linux package includes its own Python runtime and libtorrent. A system
Python installation is not required.

**macOS**

Download and extract the macOS ZIP produced for the release. macOS packages
are built on a native GitHub-hosted macOS runner and include their required
Python runtime and libtorrent binding.

## First-time setup

- Open Connection Manager: `Ctrl+Shift+C` (or tray icon -> Switch Profile -> Connection Manager...).
- Add a profile and connect:
  - **Local** — manages torrents via libtorrent on this PC (default profile on first run).
  - **Remote** — point at qBittorrent, Transmission, or rTorrent and enter credentials if needed.

## Searching for torrents

Tools -> Search for Torrents... (`Ctrl+F`) searches Knaben, The Pirate Bay, EZTV, Nyaa, Torrents-CSV, LimeTorrents and BitSearch at once, filling the list as each answers. Sort by seeders, best match, size, newest or name; `Enter` adds the selected rows to the connected client, and `Ctrl+C` copies their magnet links.

**Search sites...** switches individual indexers off, and indexers added in a later release are searched by default. **My indexers...** adds your own Torznab or Newznab endpoint — a whole Prowlarr or Jackett instance counts as one. That is how private trackers are searched: those tools already hold the login and the passkey, so SerrebiTorrent never stores a tracker password. A private tracker's authenticated `.torrent` is fetched with your own credentials at the moment you add it, rather than being turned into a magnet that its swarm would refuse.

SerrebiTorrent ships with no indexers of its own configured — only the public ones above. If [blindDL](https://github.com/serrebidev/blindDL) is installed on the same computer and has indexers set up, the search picks them up the first time it opens, since both use the same feed format. It only ever adds: an indexer you have edited here is never overwritten.

## Settings

- Local session + app settings: Tools -> Local Session Settings... (`Ctrl+,`) (or tray icon -> Settings -> Local Session Settings...).
- Remote client settings (enabled only when connected): Tools -> qBittorrent/Transmission/rTorrent Remote Settings... (or tray icon -> Settings -> ...).

## Recent save destinations

The Add Torrent dialog remembers up to 10 destination paths per connection profile. The Save Path field remains fully editable and now exposes recent destinations in a drop-down, including remote server paths exactly as entered. Choosing or typing a path does not require it to exist on the local computer, so remote qBittorrent, Transmission, and rTorrent workflows are not confused with local filesystem browsing.

## Clipboard magnets and duplicate trackers

`Ctrl+U` prefills the Add URL dialog with the first valid magnet or HTTP(S)
`.torrent` file URL from the clipboard, including URLs with query strings.
**Prefill Add URL from clipboard (magnets and .torrent URLs)** in
Tools -> Local Session Settings -> General controls this behavior and is on by
default. Turn it off to open Add URL with an empty input. No URL is fetched until
you confirm. Links without a recognizable `.torrent` filename can still be
pasted manually.

To open the Add Torrent dialog automatically when a magnet is copied, enable
**Automatically open the Add Torrent dialog for clipboard magnets** in
Tools -> Local Session Settings -> General. This app setting also applies while
connected to a remote client and is off by default. The app must be running and
connected; it can be minimized to the tray.

Each detected magnet opens the usual save-location dialog. Nothing is added
until you confirm; Cancel dismisses that clipboard content. Multiple magnets
are handled one at a time, unchanged clipboard text is not prompted repeatedly,
and magnets copied using the app's own Copy Magnet Link command are ignored.
Magnet file selection still requires metadata and is unavailable in this dialog.

The default destination is read from the connected client. For a remote client,
enter a path on that server (the Browse button browses this computer). New magnets
obey the app's Automatically start torrents setting.

For Transmission, qBittorrent, rTorrent and the built-in local session, if the torrent already exists,
the app asks whether to add the new trackers from that magnet instead. Declining
leaves it unchanged; accepting adds only missing trackers and preserves its
location and running/paused state. Links without new trackers show an
already-added message. Duplicate tracker merging currently applies to desktop
magnet additions, not `.torrent` files or RSS/web additions. Locally merged
trackers are persisted across application restarts.

Transmission file additions also preserve the checked/unchecked file selection
from the Add Torrent dialog. Transmission progress uses the selected download
size and bytes remaining, so existing data and selective downloads are reported
correctly rather than being based on lifetime downloaded traffic.

## Run from source (developers)

1. Install Python 3.14.
2. `git clone https://github.com/serrebidev/SerrebiTorrent`
3. `python -m pip install -r requirements.txt`
4. Ensure the Python 3.14 Windows `libtorrent` extension and its DLLs are installed or available on `PATH` — it isn't published on PyPI.
5. Launch it: `python main.py`

## Building

`build_exe.bat` drives releases from the Windows release machine. It creates a
clean build environment, installs the newest locally maintained CPython 3.14
libtorrent wheel, packages and verifies Windows locally, and asks
`root@serrebiradio.com` to build and verify Linux. Tagged macOS packages are
built natively by GitHub Actions.

Prereqs:
- Python 3.14
- A validated libtorrent wheel from the `Libtorrent Weekly Update` task
- Git + GitHub CLI (`gh auth login` completed)
- Code signing cert installed
- SignTool available (default path used, or set `SIGNTOOL_PATH`)

Commands:
- `build_exe.bat build` — builds, signs, and zips locally.
- `build_exe.bat release` — auto-bumps, builds Windows locally and Linux over SSH, signs, archives, tags, pushes, creates the GitHub release, and uploads the update manifest.
- `build_exe.bat dry-run` — shows what it would do without modifying anything.
- `powershell -File tools\build_linux_remote.ps1 -Version X.Y.Z` — builds only the Linux package on the configured SSH host.

Versioning uses the latest `vMAJOR.MINOR.PATCH` tag as the base. If none exists, it starts at `v1.0.0`. Commits with `BREAKING CHANGE` or `!:` bump major; commits starting with `feat` (or containing `feature`) bump minor; otherwise it bumps patch.

Windows output lands in `dist\SerrebiTorrent\`; distribute the whole folder,
not just the EXE. The package contains its own Python runtime, libtorrent, and
the native libraries those features actually load, so users do not install
Python or a Visual C++ runtime separately.

## Auto-updater

The app checks GitHub Releases for updates. Enable or disable the startup check in Local Session Settings, or run Tools -> Check for Updates at any time.

Update flow:
1. Downloads the release ZIP using the update manifest asset (`SerrebiTorrent-update.json`).
2. Verifies the ZIP's SHA-256 against the manifest.
3. Verifies the Authenticode signature on the new `SerrebiTorrent.exe`.
4. Runs a hidden helper script that waits for the app to exit, backs up the current install to `<install_dir>_backup_<timestamp>`, swaps in the new files, and restarts the app.

Backup cleanup runs automatically:
- **Default** — keeps 1 backup (newest); cleanup starts after a 5-minute grace period.
- **Immediate** — set `SERREBITORRENT_KEEP_BACKUPS=0` to delete the backup right after a successful update.
- **Multiple** — set `SERREBITORRENT_KEEP_BACKUPS=N` to keep N most recent backups.

Other environment variables:
- `SERREBITORRENT_TRUSTED_SIGNING_THUMBPRINTS` — comma-separated list of trusted certificate thumbprints.

If an update fails, the backup is restored automatically. Check the updater log in `%TEMP%\SerrebiTorrent_update_*.log` if something goes wrong. The update process runs completely hidden — no console windows appear, and user data in `SerrebiTorrent_Data` is preserved throughout.

## Download completion automation

Local Session Settings includes **Pause torrents when downloads complete**. It is off by default. When enabled, SerrebiTorrent pauses only torrents that transition from incomplete to complete while the current profile is active; already-complete torrents are not paused on startup or profile switch.

**Show a system notification when downloads complete** is also off by default. Enable it when you want a native desktop notification while SerrebiTorrent is minimized or in the tray. This is independent from the screen-reader completion announcement.

## Automatic completed-download moves

Local Session Settings includes **Move completed torrent data to**. Leave it blank to keep the feature disabled. When set, SerrebiTorrent moves each newly completed torrent to that destination using the connected client's storage-move API. For remote qBittorrent or Transmission profiles, enter a path valid on the remote server; SerrebiTorrent intentionally uses a text field rather than a local folder picker.

The automatic move uses the same capability layer as the manual Move torrent data action, so it works with qBittorrent, Transmission, and the built-in libtorrent client. rTorrent reports the unsupported capability instead of silently pretending to move data. If **Pause torrents when downloads complete** is also enabled, SerrebiTorrent performs the move first and then pauses the torrent in the same background worker to avoid racing the two automations.

## Seed ratio automation

Local Session Settings includes **Pause seeding when ratio reaches**. Set a decimal target such as `2.0` to have SerrebiTorrent automatically pause completed, active torrents when their upload ratio reaches the target. `0` disables the automation. The rule is implemented at the SerrebiTorrent layer, so it behaves consistently across local libtorrent, qBittorrent, Transmission, and rTorrent, and successful automatic pauses are recorded in Activity History.

## Disk-space protection

Local Session Settings includes **Minimum free space reserve (MiB, 0 disables protection)**. The default is 0, so existing behavior does not change until the user enables it. For .torrent files, SerrebiTorrent calculates the bytes actually selected for download before adding the torrent and refuses the add when it would cross the configured free-space reserve.

The same reserve is enforced continuously while downloads are active. Once a torrent has metadata and a known save path, SerrebiTorrent checks free space in the background during normal refreshes. If a destination reaches the configured reserve, active incomplete torrents writing there are paused automatically, the event is announced to screen readers, and it is recorded in Activity History. Free space is queried once per destination per guard pass, and transient query failures are skipped rather than interrupting normal refreshes.

The check supports the built-in libtorrent client and arbitrary Transmission download paths. qBittorrent exposes free space for its default save path, so protection is available there when that path is used. rTorrent does not expose a reliable cross-client free-space query and reports the limitation instead. Magnet links are not preflighted because their payload size is unknown until metadata arrives.

## Safe stalled-torrent recovery

After using **Diagnose Torrent**, you can run **Actions > Try to Fix Stalled Torrent** (`Ctrl+Shift+D`) on one or more selected torrents. SerrebiTorrent only targets incomplete torrents that are not checking and are not already receiving data. The recovery action runs in the background, asks the client to start/resume the torrent, and forces a tracker reannounce. It deliberately does **not** start a recheck, because verification can be expensive and should remain an explicit user action.

## Torrent categories

SerrebiTorrent provides its own profile-scoped torrent categories so the experience is consistent across local libtorrent, qBittorrent, Transmission, and rTorrent. Select one or more torrents and use **Actions > Set Category...** (`Ctrl+Alt+C`) to assign a category, or **Clear Category** to remove it. Categories appear in the sidebar with live counts and combine with the existing name filter. Category metadata is stored locally under the SerrebiTorrent state directory and does not modify backend-specific labels or tags.

## Activity history

SerrebiTorrent keeps up to 500 recent user-facing events in `SerrebiTorrent_Data/state/activity_history.json` (or the per-user state directory in installed mode). **Tools > Activity History** (`Ctrl+Shift+H`) shows the newest events first in a keyboard- and screen-reader-friendly list. The history records connections, completed downloads, successful actions, watch-folder results, and user-facing errors; it intentionally excludes noisy technical backend logging. Use **Clear History** in the dialog to reset it.

## Accessibility and shortcuts

Everything stays reachable by keyboard:

- `Ctrl+Shift+C` — Connection Manager
- `Ctrl+O` / `Ctrl+U` — Add torrent file / Add URL or magnet
- `Ctrl+S` / `Ctrl+P` — Start / Stop selected torrents
- `Ctrl+Alt+S` / `Ctrl+Alt+P` — Start / Stop all torrents
- `Ctrl+Alt+Home` / `Ctrl+Alt+End` — Move selected torrents to the top / bottom of the queue
- `Ctrl+Alt+Up` / `Ctrl+Alt+Down` — Move selected torrents up / down in the queue
- `Ctrl+D` — Diagnose the selected torrent and explain common stalled-download causes
- `Ctrl+Shift+D` — Try safe recovery actions for selected stalled torrents (resume/start + tracker reannounce)
- **Actions > Move torrent data...** — Move selected torrent data to another folder on qBittorrent, Transmission, or the built-in libtorrent client
- `Ctrl+Alt+L` — Set per-torrent download/upload speed limits in bytes/s (0 = unlimited) on qBittorrent, Transmission, or the built-in libtorrent client
- `Ctrl+Alt+C` — Assign a SerrebiTorrent category to selected torrents
- `Delete` / `Shift+Delete` — Remove / Remove with data
- `Ctrl+A` — Select all
- `Ctrl+N` — Create a torrent
- `Ctrl+F` — Search for torrents
- `Ctrl+L` — Filter the current torrent list by name
- `Ctrl+Shift+L` — Clear the torrent name filter
- `Ctrl+Shift+H` — Open the persistent activity history
- `Tab` — Toggle focus between the sidebar and torrent list; double-clicking the tray icon restores the window.

Local libtorrent errors, state changes, and recheck completion are recorded in `SerrebiTorrent_Data\logs\session.log` (or the per-user app data folder in installed mode). The log keeps two rotated backups. If a torrent stays incomplete after Force Recheck, compare its save path and files with the errors in this log.

## Contributing

Pull requests are welcome. If SerrebiTorrent has been useful to you, open a PR with a fix or feature and I'll review it.

## Community and support

Report bugs and request features in [Issues](https://github.com/serrebidev/SerrebiTorrent/issues). For questions, feedback, and release news, join the [SerrebiProjects Telegram group](https://t.me/SerrebiProjects).
