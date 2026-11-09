"""Publish a SerrebiTorrent release to Forgejo.

Runs the draft -> upload -> publish -> sweep -> verify flow that
build_exe.bat used to perform with `gh release`, against the Forgejo
API. Authentication comes from the FORGEJO_TOKEN environment variable.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

API_TIMEOUT = 30
UPLOAD_TIMEOUT = 300
ATTACHMENT_FIELD = "attachment"


class ReleaseError(RuntimeError):
    """A release step failed; the message is safe to show the user."""


class ForgejoClient:
    """Minimal Forgejo releases client with an injectable session for tests."""

    def __init__(self, host: str, repo: str, token: str, session=None):
        self.base = f"https://{host}/api/v1/repos/{repo}"
        self.token = token
        self.session = session if session is not None else requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {"Accept": "application/json", "Authorization": f"token {self.token}"}

    def _request(self, method: str, path: str, ok_404: bool = False, **kwargs):
        url = f"{self.base}{path}"
        try:
            response = self.session.request(
                method, url, headers=self._headers(), timeout=API_TIMEOUT, **kwargs
            )
        except Exception as exc:
            raise ReleaseError(f"Network error calling Forgejo {method} {path}: {exc}") from exc
        if response.status_code == 404 and ok_404:
            return None
        if response.status_code >= 400:
            raise ReleaseError(
                f"Forgejo API error: {method} {path}: "
                f"{response.status_code} {response.reason}"
            )
        if response.status_code == 204 or not getattr(response, "content", b""):
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ReleaseError(
                f"Failed to parse Forgejo API response for {method} {path}: {exc}"
            ) from exc

    def get_release_by_tag(self, tag: str) -> Optional[Dict[str, Any]]:
        return self._request("GET", f"/releases/tags/{tag}", ok_404=True)

    def list_releases(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._request("GET", "/releases", params={"limit": limit}) or []

    def create_release(self, tag: str, title: str, notes: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/releases",
            json={"tag_name": tag, "name": title, "body": notes, "draft": True},
        )

    def publish_release(self, release_id: int) -> Dict[str, Any]:
        return self._request("PATCH", f"/releases/{release_id}", json={"draft": False})

    def delete_release(self, release_id: int) -> None:
        self._request("DELETE", f"/releases/{release_id}")

    def upload_asset(self, release_id: int, asset: Path) -> Dict[str, Any]:
        name = asset.name
        content_type = "application/json" if asset.suffix == ".json" else "application/octet-stream"
        with asset.open("rb") as handle:
            files = {ATTACHMENT_FIELD: (name, handle, content_type)}
            try:
                response = self.session.request(
                    "POST",
                    f"{self.base}/releases/{release_id}/assets",
                    headers=self._headers(),
                    params={"name": name},
                    files=files,
                    timeout=UPLOAD_TIMEOUT,
                )
            except Exception as exc:
                raise ReleaseError(f"Network error uploading {name}: {exc}") from exc
        if response.status_code >= 400:
            raise ReleaseError(
                f"Forgejo API error uploading {name}: {response.status_code} {response.reason}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ReleaseError(f"Failed to parse Forgejo upload response for {name}: {exc}") from exc

    def latest_tag(self) -> Optional[str]:
        data = self._request("GET", "/releases/latest")
        return (data or {}).get("tag_name")


def draft_ids(releases: List[Dict[str, Any]]) -> List[int]:
    """IDs of draft releases. Tags are never touched, only release rows."""
    return [release["id"] for release in releases if release.get("draft")]


def sweep_drafts(client: ForgejoClient) -> None:
    for release_id in draft_ids(client.list_releases()):
        print(f"Deleting draft release {release_id}...")
        client.delete_release(release_id)


def publish(
    client: ForgejoClient, tag: str, title: str, notes: str, assets: List[Path]
) -> Dict[str, Any]:
    existing = client.get_release_by_tag(tag)
    if existing is not None and not existing.get("draft"):
        raise ReleaseError(f"Release {tag} is already published; refusing to overwrite it.")
    sweep_drafts(client)
    print(f"Creating draft release {tag}...")
    release = client.create_release(tag, title, notes)
    release_id = release["id"]
    try:
        for asset in assets:
            print(f"Uploading {asset.name}...")
            client.upload_asset(release_id, asset)
        print(f"Publishing {tag}...")
        client.publish_release(release_id)
    except ReleaseError:
        print(f"Cleaning up draft release {tag} after failure...")
        client.delete_release(release_id)
        raise
    sweep_drafts(client)
    return release


def verify_latest(client: ForgejoClient, tag: str) -> None:
    print(f"Verifying Forgejo /releases/latest points to {tag}...")
    actual = client.latest_tag()
    if actual is None:
        raise ReleaseError(f"Failed to read Forgejo /releases/latest for {tag}.")
    if actual != tag:
        raise ReleaseError(
            f"Forgejo /releases/latest is {actual}, expected {tag}.\n"
            "The updater will keep reporting the old release until this is corrected."
        )
    print(f"Forgejo latest release is {tag}.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Publish a SerrebiTorrent release to Forgejo.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--notes-file", required=True)
    parser.add_argument("--assets", nargs="+", required=True)
    args = parser.parse_args(argv)

    token = os.environ.get("FORGEJO_TOKEN", "").strip()
    if not token:
        print(
            "ERROR: FORGEJO_TOKEN is not set. Copy it from "
            "/root/forgejo-muse-token.txt on root@serrebiradio.com.",
            file=sys.stderr,
        )
        return 1
    try:
        notes = Path(args.notes_file).read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        print(f"ERROR: cannot read notes file: {exc}", file=sys.stderr)
        return 1
    assets = []
    for raw in args.assets:
        path = Path(raw)
        if not path.is_file():
            print(f"ERROR: release asset not found: {raw}", file=sys.stderr)
            return 1
        assets.append(path)
    client = ForgejoClient(args.host, args.repo, token)
    try:
        publish(client, args.tag, args.title, notes, assets)
        verify_latest(client, args.tag)
    except ReleaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
