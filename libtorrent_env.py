"""Helpers for making sure libtorrent's dependent DLLs are discoverable on Windows."""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Iterable, List, Set

_BOOTSTRAPPED = False
_DLL_DIRECTORY_HANDLES = []


def _unique_existing_paths(paths: Iterable[str | None]) -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for raw in paths:
        if not raw:
            continue
        path = os.path.abspath(raw)
        if path in seen:
            continue
        if os.path.isdir(path):
            ordered.append(path)
            seen.add(path)
    return ordered


def prepare_libtorrent_dlls() -> None:
    """
    Ensure directories that contain libtorrent and its OpenSSL dependencies are part of the
    DLL search path before attempting to import libtorrent.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED or sys.platform != "win32":
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    cwd = os.getcwd()
    python_dlls = os.path.join(sys.base_prefix, "DLLs")
    
    # Handle PyInstaller _MEIPASS
    meipass_dir = getattr(sys, '_MEIPASS', None)

    # Try to locate the directory that contains the libtorrent extension itself.
    libtorrent_dir = None
    try:
        spec = importlib.util.find_spec("libtorrent")
    except (ImportError, ValueError):
        spec = None

    if spec and spec.origin:
        libtorrent_dir = os.path.dirname(spec.origin)

    candidate_dirs = _unique_existing_paths(
        [
            cwd,
            script_dir,
            meipass_dir, # Add PyInstaller temp dir
            python_dlls,
            libtorrent_dir,
            os.environ.get("LIBTORRENT_DLL_DIR"),
        ]
    )

    if not candidate_dirs:
        _BOOTSTRAPPED = True
        return

    existing_path = os.environ.get("PATH", "")
    path_parts = existing_path.split(os.pathsep) if existing_path else []

    for path in candidate_dirs:
        if path not in path_parts:
            path_parts.insert(0, path)
        if hasattr(os, "add_dll_directory"):
            try:
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(path))
            except (FileNotFoundError, OSError):
                pass

    os.environ["PATH"] = os.pathsep.join(path_parts)
    _BOOTSTRAPPED = True
