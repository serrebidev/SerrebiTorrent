from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple
from urllib.parse import urlparse

import requests

from app_version import APP_VERSION

GITHUB_OWNER = "serrebidev"
GITHUB_REPO = "SerrebiTorrent"
UPDATE_MANIFEST_ASSET = "SerrebiTorrent-update.json"
APP_EXE_NAME = "SerrebiTorrent.exe"

API_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 60
MAX_UPDATE_MANIFEST_BYTES = 1024 * 1024
MAX_UPDATE_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_UPDATE_ZIP_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_UPDATE_ZIP_MEMBER_BYTES = 512 * 1024 * 1024
MAX_UPDATE_ZIP_MEMBERS = 20000
BACKUP_RETENTION_GRACE_SECONDS = 300

_SEMVER_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
_STRICT_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


def _normalize_thumbprint(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.replace(" ", "").strip().upper()


def _normalize_thumbprints(values: Iterable[str]) -> Tuple[str, ...]:
    normalized = {_normalize_thumbprint(value) for value in values if value}
    normalized.discard("")
    return tuple(sorted(normalized))


def _env_thumbprints() -> Tuple[str, ...]:
    raw = os.environ.get("SERREBITORRENT_TRUSTED_SIGNING_THUMBPRINTS", "")
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _extract_manifest_thumbprints(manifest: Dict[str, Any]) -> Tuple[str, ...]:
    raw = manifest.get("signing_thumbprints") or manifest.get("signing_thumbprint")
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if item)
    return ()


def get_allowed_thumbprints(manifest: Dict[str, Any]) -> Tuple[str, ...]:
    return _normalize_thumbprints(list(_extract_manifest_thumbprints(manifest)) + list(_env_thumbprints()))


def _dedupe_paths(paths: Iterable[str]) -> Tuple[str, ...]:
    seen = set()
    out = []
    for path in paths:
        raw = str(path or "").strip()
        if not raw:
            continue
        key = os.path.normcase(os.path.abspath(raw))
        if key in seen:
            continue
        seen.add(key)
        out.append(raw)
    return tuple(out)


def _powershell_executables() -> Tuple[str, ...]:
    candidates = []
    for name in ("pwsh", "powershell"):
        path = shutil.which(name)
        if path:
            candidates.append(path)

    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    candidates.extend(
        [
            os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
            os.path.join(system_root, "Sysnative", "WindowsPowerShell", "v1.0", "powershell.exe"),
        ]
    )
    return _dedupe_paths(path for path in candidates if os.path.isfile(path) or shutil.which(path))


def _ps_single_quote(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _hidden_subprocess_kwargs() -> Dict[str, Any]:
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        "startupinfo": startupinfo,
    }


class UpdateError(Exception):
    pass


class RateLimitError(UpdateError):
    pass


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str
    manifest: Dict[str, Any]
    release: Dict[str, Any]


@dataclass
class UpdateCheckResult:
    status: str
    message: str
    info: Optional[UpdateInfo] = None


UPDATE_CANCELED_MESSAGE = "Update canceled."


def parse_semver(text: str) -> Optional[Tuple[int, int, int]]:
    if not text:
        return None
    match = _STRICT_SEMVER_RE.match(text.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def format_version(value: Tuple[int, int, int]) -> str:
    return f"{value[0]}.{value[1]}.{value[2]}"


def is_newer_version(current: Tuple[int, int, int], latest: Tuple[int, int, int]) -> bool:
    return latest > current


def _is_sha256(value: str) -> bool:
    return bool(value) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def _is_thumbprint(value: str) -> bool:
    return bool(value) and re.fullmatch(r"[0-9A-F]{40}", value) is not None


def _validate_published_at(value: Any) -> None:
    text = str(value or "").strip()
    if not text:
        raise UpdateError("Update manifest has an invalid published_at timestamp.")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise UpdateError("Update manifest has an invalid published_at timestamp.") from exc


def _validate_download_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or host not in _ALLOWED_DOWNLOAD_HOSTS:
        raise UpdateError("Update download URL must be an HTTPS GitHub release asset.")


def _rate_limit_message(headers: Mapping[str, str]) -> str:
    reset = headers.get("X-RateLimit-Reset")
    if reset and reset.isdigit():
        reset_dt = datetime.datetime.utcfromtimestamp(int(reset))
        return f"GitHub API rate limit reached. Try again after {reset_dt:%Y-%m-%d %H:%M:%SZ}."
    return "GitHub API rate limit reached. Try again later."


def fetch_latest_release() -> Dict[str, Any]:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "SerrebiTorrent-Updater",
    }
    try:
        response = requests.get(url, headers=headers, timeout=API_TIMEOUT)
    except requests.RequestException as exc:
        raise UpdateError(f"Network error while contacting GitHub: {exc}") from exc
    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        raise RateLimitError(_rate_limit_message(response.headers))
    if response.status_code != 200:
        raise UpdateError(f"GitHub API error: {response.status_code} {response.reason}")
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise UpdateError(f"Failed to parse GitHub API response: {exc}") from exc


def _find_asset(release: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    for asset in release.get("assets", []) or []:
        if asset.get("name") == name:
            return asset
    return None


def download_manifest(release: Dict[str, Any]) -> Dict[str, Any]:
    asset = _find_asset(release, UPDATE_MANIFEST_ASSET)
    if not asset:
        raise UpdateError("Update manifest not found in the latest release.")
    url = asset.get("browser_download_url")
    if not url:
        raise UpdateError("Update manifest asset is missing a download URL.")
    _validate_download_url(str(url))
    try:
        response = requests.get(url, timeout=API_TIMEOUT, stream=True)
    except requests.RequestException as exc:
        raise UpdateError(f"Network error while downloading manifest: {exc}") from exc
    try:
        if response.status_code != 200:
            raise UpdateError(f"Failed to download update manifest: {response.status_code}")
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                expected_size = int(content_length)
            except ValueError as exc:
                raise UpdateError("Update manifest returned an invalid Content-Length.") from exc
            if expected_size < 0 or expected_size > MAX_UPDATE_MANIFEST_BYTES:
                raise UpdateError("Update manifest is larger than the allowed size.")
        content = b""
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            content += chunk
            if len(content) > MAX_UPDATE_MANIFEST_BYTES:
                raise UpdateError("Update manifest is larger than the allowed size.")
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError(f"Update manifest is not valid JSON: {exc}") from exc
    finally:
        response.close()


def validate_manifest(manifest: Dict[str, Any], release: Dict[str, Any]) -> Dict[str, Any]:
    missing = [k for k in ("version", "asset_filename", "download_url", "sha256", "published_at") if k not in manifest]
    if missing:
        raise UpdateError(f"Update manifest missing required fields: {', '.join(missing)}")

    if not _is_sha256(str(manifest.get("sha256", ""))):
        raise UpdateError("Update manifest has an invalid sha256 checksum.")
    _validate_published_at(manifest.get("published_at"))
    manifest_thumbprints = _normalize_thumbprints(_extract_manifest_thumbprints(manifest))
    if not manifest_thumbprints or any(not _is_thumbprint(tp) for tp in manifest_thumbprints):
        raise UpdateError("Update manifest has an invalid signing thumbprint.")

    release_tag = release.get("tag_name", "")
    manifest_version = parse_semver(str(manifest.get("version", "")))
    release_version = parse_semver(release_tag)
    if not manifest_version:
        raise UpdateError("Update manifest version is not a semver version.")
    if not release_version:
        raise UpdateError("Latest release tag is not a semver version.")
    if manifest_version != release_version:
        raise UpdateError("Update manifest version does not match the latest release tag.")

    asset = _find_asset(release, str(manifest.get("asset_filename", "")))
    if not asset or not asset.get("browser_download_url"):
        raise UpdateError("Update asset not found in the latest release.")
    asset_url = str(asset["browser_download_url"])
    _validate_download_url(asset_url)

    if not manifest.get("download_url"):
        manifest["download_url"] = asset_url
    elif str(manifest.get("download_url")) != asset_url:
        raise UpdateError("Update manifest download URL does not match the release asset.")
    _validate_download_url(str(manifest["download_url"]))

    return manifest


def check_for_updates() -> UpdateCheckResult:
    current_tuple = parse_semver(APP_VERSION)
    if not current_tuple:
        return UpdateCheckResult("error", f"Current app version is not semver: {APP_VERSION}")
    try:
        release = fetch_latest_release()
        tag = str(release.get("tag_name", "")).strip()
        latest_tuple = parse_semver(tag)
        if not latest_tuple:
            return UpdateCheckResult("error", f"Latest release tag is not semver: {tag}")
        if not is_newer_version(current_tuple, latest_tuple):
            return UpdateCheckResult("up_to_date", f"SerrebiTorrent is up to date (v{format_version(current_tuple)}).")

        manifest = validate_manifest(download_manifest(release), release)
        latest_version = format_version(latest_tuple)
        info = UpdateInfo(
            current_version=APP_VERSION,
            latest_version=latest_version,
            manifest=manifest,
            release=release,
        )
        return UpdateCheckResult("update_available", "Update available.", info)
    except RateLimitError as exc:
        return UpdateCheckResult("rate_limited", str(exc))
    except UpdateError as exc:
        return UpdateCheckResult("error", str(exc))
    except Exception as exc:
        return UpdateCheckResult("error", f"Update check failed: {exc}")


def check_for_update() -> Optional[UpdateInfo]:
    result = check_for_updates()
    if result.status == "update_available":
        return result.info
    if result.status == "up_to_date":
        return None
    if result.status == "rate_limited":
        raise RateLimitError(result.message)
    raise UpdateError(result.message)


def download_file(url: str, dest_path: str, progress_cb=None) -> None:
    _validate_download_url(url)
    try:
        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as response:
            if response.status_code != 200:
                raise UpdateError(f"Download failed: {response.status_code} {response.reason}")
            expected_size = None
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    expected_size = int(content_length)
                except ValueError as exc:
                    raise UpdateError("Update download returned an invalid Content-Length.") from exc
                if expected_size < 0:
                    raise UpdateError("Update download returned an invalid Content-Length.")
                if expected_size > MAX_UPDATE_DOWNLOAD_BYTES:
                    raise UpdateError("Update download is larger than the allowed size.")
            try:
                written = 0
                with open(dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > MAX_UPDATE_DOWNLOAD_BYTES:
                            raise UpdateError("Update download is larger than the allowed size.")
                        f.write(chunk)
                        if progress_cb is not None:
                            try:
                                keep_going = progress_cb(written, expected_size)
                            except Exception:
                                keep_going = True
                            if keep_going is False:
                                raise UpdateError(UPDATE_CANCELED_MESSAGE)
            except Exception:
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
                raise
    except requests.RequestException as exc:
        raise UpdateError(f"Network error while downloading update: {exc}") from exc


def compute_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_zip(zip_path: str, dest_dir: str) -> None:
    dest_abs = os.path.abspath(dest_dir)
    dest_norm = os.path.normcase(dest_abs)
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        if len(members) > MAX_UPDATE_ZIP_MEMBERS:
            raise UpdateError("Update archive contains too many files.")
        total_size = 0
        for member in members:
            member_name = member.filename.replace("\\", "/")
            target = os.path.abspath(os.path.join(dest_abs, member_name))
            target_norm = os.path.normcase(target)
            try:
                common = os.path.commonpath([dest_norm, target_norm])
            except ValueError as exc:
                raise UpdateError(f"Unsafe path in update archive: {member.filename}") from exc
            if common != dest_norm:
                raise UpdateError(f"Unsafe path in update archive: {member.filename}")
            if member.file_size > MAX_UPDATE_ZIP_MEMBER_BYTES:
                raise UpdateError("Update archive contains a file larger than the allowed size.")
            total_size += member.file_size
            if total_size > MAX_UPDATE_ZIP_UNCOMPRESSED_BYTES:
                raise UpdateError("Update archive is larger than the allowed uncompressed size.")
        zf.extractall(dest_abs)


def find_app_dir(staging_dir: str, exe_name: str = APP_EXE_NAME) -> Optional[str]:
    candidate = os.path.join(staging_dir, "SerrebiTorrent", exe_name)
    if os.path.isfile(candidate):
        return os.path.dirname(candidate)
    matches = []
    for root, dirs, files in os.walk(staging_dir):
        dirs.sort()
        files.sort()
        if exe_name in files:
            matches.append(root)
    if not matches:
        return None
    matches.sort(key=lambda p: (0 if os.path.basename(p).lower() == "serrebitorrent" else 1, len(p), p.lower()))
    return matches[0]


def verify_authenticode(exe_path: str, allowed_thumbprints: Iterable[str]) -> None:
    allowed = set(_normalize_thumbprints(allowed_thumbprints))
    if not allowed:
        raise UpdateError("No trusted Authenticode signing thumbprint is configured.")
    ps_script = (
        "$ErrorActionPreference = 'Stop';"
        "Import-Module Microsoft.PowerShell.Security -ErrorAction SilentlyContinue;"
        f"$sig = Get-AuthenticodeSignature -LiteralPath {_ps_single_quote(exe_path)};"
        "$subject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { '' };"
        "$thumb = if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { '' };"
        "$out = @{Status=$sig.Status.ToString(); StatusMessage=$sig.StatusMessage; Subject=$subject; Thumbprint=$thumb};"
        "$out | ConvertTo-Json -Compress"
    )
    last_error = ""
    for powershell_exe in _powershell_executables():
        try:
            result = subprocess.run(
                [powershell_exe, "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                check=False,
                **_hidden_subprocess_kwargs(),
            )
        except Exception as exc:
            last_error = f"{powershell_exe}: {exc}"
            continue

        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
            last_error = f"{powershell_exe}: {msg}"
            continue
        try:
            data = json.loads(result.stdout.strip())
        except json.JSONDecodeError as exc:
            last_error = f"{powershell_exe}: invalid Authenticode data: {exc}"
            continue

        status = str(data.get("Status", "")).strip()
        status_msg = str(data.get("StatusMessage", "")).strip()
        thumbprint = _normalize_thumbprint(data.get("Thumbprint"))
        status_l = status.lower()
        if status_l in ("valid", "0"):
            if not thumbprint or thumbprint not in allowed:
                detail = "Authenticode signer thumbprint is not allowed."
                if thumbprint:
                    detail = f"{detail} (thumbprint {thumbprint})"
                raise UpdateError(detail)
            return
        if status_l in ("unknownerror", "1") and thumbprint and thumbprint in allowed:
            return
        msg = status_msg or "Unknown signature status."
        detail = f"Authenticode signature is not valid: {status} {msg}".strip()
        if thumbprint:
            detail = f"{detail} (thumbprint {thumbprint})"
        raise UpdateError(detail)

    if last_error:
        raise UpdateError(f"Authenticode verification failed: {last_error}")
    raise UpdateError("Authenticode verification failed: PowerShell was not found.")


def find_update_helper(install_dir: Optional[str] = None) -> Optional[str]:
    install_dir = os.path.abspath(install_dir or os.path.dirname(sys.executable))
    candidates = [
        os.path.join(install_dir, "update_helper.bat"),
        os.path.join(install_dir, "_internal", "update_helper.bat"),
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(str(meipass), "update_helper.bat"))
    for path in _dedupe_paths(candidates):
        if os.path.isfile(path):
            return path
    return None


def is_update_supported(install_dir: Optional[str] = None) -> bool:
    if not getattr(sys, "frozen", False):
        return False
    return find_update_helper(install_dir) is not None


def _make_update_temp_root(install_dir: str) -> str:
    install_dir = os.path.abspath(str(install_dir or ""))
    parent = os.path.dirname(install_dir)
    candidates = []
    if parent:
        candidates.append(os.path.join(parent, "_SerrebiTorrent_update_tmp"))
    for base in candidates:
        try:
            os.makedirs(base, exist_ok=True)
            probe = os.path.join(base, f".probe_{os.getpid()}_{int(time.time())}")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return tempfile.mkdtemp(prefix="SerrebiTorrent_update_", dir=base)
        except Exception:
            continue
    return tempfile.mkdtemp(prefix="SerrebiTorrent_update_")


def _safe_remove_dir(path: str, install_dir: str, reason: str) -> None:
    if not path:
        return
    try:
        full_path = os.path.realpath(path)
    except Exception:
        return
    if not os.path.isdir(full_path):
        return
    try:
        install_path = os.path.realpath(install_dir)
    except Exception:
        install_path = install_dir
    target_norm = os.path.normcase(full_path)
    install_norm = os.path.normcase(install_path)
    if target_norm in (install_norm, os.path.normcase(os.path.dirname(install_path))):
        return
    if target_norm == os.path.normcase(os.path.abspath(os.sep)):
        return
    try:
        shutil.rmtree(full_path)
    except Exception:
        pass


def _backup_keep_count() -> int:
    raw = os.environ.get("SERREBITORRENT_KEEP_BACKUPS", "1")
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return 1


def _backup_dirs_for_install(install_dir: str) -> Tuple[str, ...]:
    parent_dir = os.path.dirname(install_dir)
    install_base = os.path.basename(install_dir).lower()
    prefix = f"{install_base}_backup_"
    try:
        names = os.listdir(parent_dir)
    except Exception:
        return ()
    paths = []
    for name in names:
        path = os.path.join(parent_dir, name)
        if name.lower().startswith(prefix) and os.path.isdir(path):
            paths.append(path)
    paths.sort(key=lambda p: (os.path.getmtime(p), os.path.basename(p).lower()), reverse=True)
    return tuple(paths)


def cleanup_update_artifacts(install_dir: Optional[str] = None, now: Optional[float] = None) -> None:
    if not getattr(sys, "frozen", False):
        return
    install_dir = os.path.abspath(install_dir or os.path.dirname(sys.executable))
    parent_dir = os.path.dirname(install_dir)
    keep_backups = _backup_keep_count()
    now = time.time() if now is None else now
    for index, path in enumerate(_backup_dirs_for_install(install_dir)):
        if keep_backups > 0 and index < keep_backups:
            continue
        try:
            age = now - os.path.getmtime(path)
        except Exception:
            age = BACKUP_RETENTION_GRACE_SECONDS
        if keep_backups == 0 or age >= BACKUP_RETENTION_GRACE_SECONDS:
            _safe_remove_dir(path, install_dir, "backup")
    update_tmp_parent = os.path.join(parent_dir, "_SerrebiTorrent_update_tmp")
    try:
        if os.path.isdir(update_tmp_parent):
            for entry in os.listdir(update_tmp_parent):
                if entry.startswith("SerrebiTorrent_update_"):
                    _safe_remove_dir(os.path.join(update_tmp_parent, entry), install_dir, "temp")
            if not os.listdir(update_tmp_parent):
                _safe_remove_dir(update_tmp_parent, install_dir, "temp parent")
    except Exception:
        pass
    try:
        temp_dir = tempfile.gettempdir()
        for entry in os.listdir(temp_dir):
            if entry.startswith("SerrebiTorrent_update_"):
                _safe_remove_dir(os.path.join(temp_dir, entry), install_dir, "temp")
    except Exception:
        pass


def launch_update_helper(
    helper_path: str,
    parent_pid: int,
    install_dir: str,
    staging_root: str,
    temp_root: Optional[str] = None,
) -> Tuple[bool, str]:
    try:
        helper_cwd = os.path.dirname(helper_path)
        if not helper_cwd or not os.path.isdir(helper_cwd):
            helper_cwd = tempfile.gettempdir()

        creationflags = 0
        startupinfo = None
        breakaway_flag = 0
        if sys.platform == "win32":
            create_no_window = 0x08000000
            create_new_process_group = 0x00000200
            breakaway_flag = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
            creationflags = create_no_window | create_new_process_group | breakaway_flag
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

        cmd = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/c",
            helper_path,
            str(parent_pid),
            install_dir,
            staging_root,
            APP_EXE_NAME,
        ]
        if temp_root:
            cmd.append(temp_root)

        try:
            subprocess.Popen(
                cmd,
                cwd=helper_cwd,
                creationflags=creationflags,
                startupinfo=startupinfo,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception:
            if sys.platform == "win32" and breakaway_flag:
                subprocess.Popen(
                    cmd,
                    cwd=helper_cwd,
                    creationflags=creationflags & ~breakaway_flag,
                    startupinfo=startupinfo,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
            else:
                raise
        return True, ""
    except Exception as exc:
        return False, f"Failed to start update helper: {exc}"


def download_and_apply_update(info: UpdateInfo, install_dir: Optional[str] = None, progress_cb=None) -> Tuple[bool, str]:
    def report(phase: str, fraction) -> bool:
        if progress_cb is None:
            return True
        try:
            result = progress_cb(phase, fraction)
            return result is None or bool(result)
        except Exception:
            return True

    install_dir = os.path.abspath(install_dir or os.path.dirname(sys.executable))
    if not is_update_supported(install_dir):
        return False, "Auto-update is not available for this build."

    temp_root = _make_update_temp_root(install_dir)
    extract_dir = os.path.join(temp_root, "extract")
    os.makedirs(extract_dir, exist_ok=True)
    zip_name = str(info.manifest.get("asset_filename") or f"SerrebiTorrent-v{info.latest_version}.zip")
    zip_path = os.path.join(temp_root, zip_name)

    success = False
    try:
        if not report("Downloading update...", 0.0):
            return False, UPDATE_CANCELED_MESSAGE
        def download_progress(written, total):
            fraction = None
            if total:
                fraction = min(0.70, max(0.0, (float(written) / float(total)) * 0.70))
            return report("Downloading update...", fraction)

        download_file(str(info.manifest.get("download_url")), zip_path, progress_cb=download_progress)

        if not report("Verifying download...", 0.75):
            return False, UPDATE_CANCELED_MESSAGE
        expected = str(info.manifest.get("sha256", "")).lower()
        actual = compute_sha256(zip_path).lower()
        if expected != actual:
            return False, "Downloaded update failed SHA-256 verification."

        if not report("Extracting update...", 0.85):
            return False, UPDATE_CANCELED_MESSAGE
        extract_zip(zip_path, extract_dir)
        new_dir = find_app_dir(extract_dir)
        if not new_dir:
            return False, "Extracted update does not contain application files."
        new_exe = os.path.join(new_dir, APP_EXE_NAME)
        if not os.path.isfile(new_exe):
            return False, "Updated executable not found."

        if not report("Verifying signature...", 0.93):
            return False, UPDATE_CANCELED_MESSAGE
        verify_authenticode(new_exe, get_allowed_thumbprints(info.manifest))

        helper_src = find_update_helper(new_dir) or find_update_helper(install_dir)
        if not helper_src:
            return False, "Update helper script not found."
        helper_run_path = os.path.join(temp_root, "update_helper.bat")
        try:
            shutil.copy2(helper_src, helper_run_path)
        except Exception:
            helper_run_path = helper_src

        if not report("Preparing restart...", 0.98):
            return False, UPDATE_CANCELED_MESSAGE
        ok, msg = launch_update_helper(helper_run_path, os.getpid(), install_dir, new_dir, temp_root=temp_root)
        if not ok:
            return False, msg
        success = True
        return True, "Update prepared. The app will restart after it exits."
    except UpdateError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Update failed: {exc}"
    finally:
        # On success the spawned helper owns temp_root (extracted files + helper
        # copy) and cleans it up after restart; on any failure/cancel path remove
        # it now so a failed update doesn't leak the ZIP + extracted tree.
        if not success:
            _safe_remove_dir(temp_root, install_dir, "failed update temp")


def build_update_prompt(info: UpdateInfo) -> str:
    notes = str(info.manifest.get("notes_summary") or "").strip()
    if len(notes) > 1200:
        notes = notes[:1200].rstrip() + "..."
    details = f"Current version: v{info.current_version}\nLatest version: v{info.latest_version}"
    if notes:
        return f"{details}\n\nRelease summary:\n{notes}\n\nDownload and install now?"
    return f"{details}\n\nDownload and install now?"
