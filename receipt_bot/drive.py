"""Google Drive via rclone (remote `gdrive:`, full scope). Never overwrites, never deletes:
uploads/moves pick a free name first and also pass --ignore-existing as a guard."""
from __future__ import annotations

import json
import os
import subprocess
from collections import Counter

RCLONE = os.environ.get("RECEIPT_BOT_RCLONE", "/usr/local/bin/rclone")
ROOT = os.environ.get("RECEIPT_BOT_DRIVE_ROOT", "gdrive:ScanSnap/Receipts")
CUT, DONE, REVIEW = "Cut", "Done", "Needs-Review"


class DriveError(RuntimeError):
    pass


def _rc(*args: str, timeout: int = 300) -> str:
    r = subprocess.run([RCLONE, *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise DriveError(f"rclone {args[0]} failed ({r.returncode}): {r.stderr.strip()[-400:]}")
    return r.stdout


def _p(*parts: str) -> str:
    return "/".join([ROOT.rstrip("/"), *parts])


def list_incoming() -> list[dict]:
    """Top-level files in Receipts/ (subfolders such as Cut/ Done/ are not descended)."""
    items = json.loads(_rc("lsjson", "--files-only", "--max-depth", "1", "--no-mimetype", _p()) or "[]")
    for i in items:  # local sandbox roots have no Drive IDs
        i.setdefault("ID", "local-" + i["Name"])
    return items


def duplicate_names(items: list[dict]) -> list[str]:
    return [n for n, c in Counter(i["Name"] for i in items).items() if c > 1]


def dedupe_rename() -> None:
    """Two scans with one name (e.g. two vendor-less receipts the same day → `10062026.jpg`)
    can't be moved by name; rclone renames the extras to `name-1.jpg`… — nothing is deleted."""
    _rc("dedupe", "--dedupe-mode", "rename", "--max-depth", "1", _p())


def ensure_folders() -> None:
    for f in (CUT, DONE, REVIEW):
        _rc("mkdir", _p(f))


def names_in(folder: str) -> set[str]:
    return set(_rc("lsf", "--files-only", _p(folder)).splitlines())


def free_name(name: str, taken: set[str], tag: str) -> str:
    if name not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    for i in range(2, 100):
        cand = f"{stem}_{i}" + (f".{ext}" if ext else "")
        if cand not in taken:
            return cand
    return f"{stem}_{tag}" + (f".{ext}" if ext else "")


def is_local() -> bool:
    """A local-path root (sandbox/tests) instead of a remote like gdrive:…"""
    return ROOT.startswith("/") or ":" not in ROOT


def download(file_id: str, name: str, dest_dir: str, folder: str | None = None) -> str:
    """Download by Drive ID (immune to duplicate names) — or by name from a subfolder
    (Needs-Review/) / a local sandbox root. Returns the local path."""
    os.makedirs(dest_dir, exist_ok=True)
    if folder or is_local() or not file_id:
        _rc("copyto", _p(*([folder] if folder else []), name), os.path.join(dest_dir, name))
    else:
        _rc("backend", "copyid", ROOT.split(":")[0] + ":", file_id, dest_dir + "/")
    path = os.path.join(dest_dir, name)
    if not os.path.exists(path):
        got = [f for f in os.listdir(dest_dir) if not f.startswith(".")]
        raise DriveError(f"download of {name} produced {got}")
    return path


def upload(local: str, folder: str, name: str, tag: str) -> str:
    """Upload to Receipts/<folder>/ under `name` (or a free variant). Returns the final name."""
    final = free_name(name, names_in(folder), tag)
    _rc("copyto", "--ignore-existing", local, _p(folder, final))
    return final


def move(name: str, folder: str, tag: str, src_folder: str | None = None) -> str:
    """Server-side move Receipts/[src_folder/]<name> → Receipts/<folder>/<name or free variant>."""
    final = free_name(name, names_in(folder), tag)
    _rc("moveto", "--ignore-existing", _p(*([src_folder] if src_folder else []), name), _p(folder, final))
    return final


def exists_top(name: str) -> bool:
    return name in set(_rc("lsf", "--files-only", "--max-depth", "1", _p()).splitlines())
