# Copyright (c) serrebidev and contributors
# SPDX-License-Identifier: MIT

"""Helpers for continuous disk-space protection."""

from __future__ import annotations


def active_download_groups(torrents):
    """Group active incomplete torrents by save path.

    Torrents without metadata/size or without a usable save path are skipped.
    The caller can then query free space once per destination.
    """
    groups = {}
    for torrent in torrents or []:
        if not isinstance(torrent, dict):
            continue

        torrent_hash = str(torrent.get("hash") or "").strip()
        save_path = str(torrent.get("save_path") or "").strip()
        if not torrent_hash or not save_path:
            continue

        try:
            state = int(torrent.get("state") or 0)
            size = int(torrent.get("size") or 0)
            done = int(torrent.get("done") or 0)
        except (TypeError, ValueError):
            continue

        if state != 1 or size <= 0 or done >= size:
            continue

        groups.setdefault(save_path, []).append(
            {
                "hash": torrent_hash,
                "name": str(torrent.get("name") or torrent_hash),
            }
        )
    return groups
