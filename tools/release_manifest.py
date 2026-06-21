import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_notes(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _parse_signtool_thumbprint(signtool_path: Path, exe_path: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            [str(signtool_path), "verify", "/pa", "/v", str(exe_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    data = (result.stdout or "") + (result.stderr or "")
    match = re.search(r"SHA1 hash:\s*([0-9A-Fa-f]{40})", data)
    if not match:
        return None
    return _normalize_thumbprint(match.group(1))


def _normalize_thumbprint(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    thumbprint = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"[0-9A-F]{40}", thumbprint):
        return None
    return thumbprint


def build_manifest(
    *,
    version: str,
    asset_name: str,
    download_url: str,
    zip_path: Path,
    notes_path: Path,
    signtool_path: Path,
    exe_path: Path,
    signing_thumbprint: Optional[str],
    output_path: Path,
) -> None:
    sha256 = _sha256_file(zip_path)
    notes = _read_notes(notes_path)
    published_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest = {
        "version": version,
        "asset_filename": asset_name,
        "download_url": download_url,
        "sha256": sha256,
        "published_at": published_at,
        "notes_summary": notes,
    }
    thumbprint = _normalize_thumbprint(signing_thumbprint) or _parse_signtool_thumbprint(signtool_path, exe_path)
    if not thumbprint:
        raise RuntimeError(
            "Failed to capture Authenticode signing thumbprint. "
            "Pass --signing-thumbprint or verify SignTool can read the signed executable."
        )
    manifest["signing_thumbprint"] = thumbprint
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SerrebiTorrent update manifest.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--asset-name", required=True)
    parser.add_argument("--download-url", required=True)
    parser.add_argument("--zip-path", required=True)
    parser.add_argument("--notes-path", required=True)
    parser.add_argument("--signtool-path", required=True)
    parser.add_argument("--exe-path", required=True)
    parser.add_argument("--signing-thumbprint")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        build_manifest(
            version=args.version,
            asset_name=args.asset_name,
            download_url=args.download_url,
            zip_path=Path(args.zip_path),
            notes_path=Path(args.notes_path),
            signtool_path=Path(args.signtool_path),
            exe_path=Path(args.exe_path),
            signing_thumbprint=args.signing_thumbprint,
            output_path=Path(args.output),
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
