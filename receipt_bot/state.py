"""Local state so nothing is processed twice. Keyed by Drive file ID (unique even when two
scans share a name). Written atomically after every step."""
from __future__ import annotations

import json
import os
import time

DEFAULT = os.path.expanduser(os.environ.get("RECEIPT_BOT_STATE", "~/.local/state/receipt-bot/state.json"))

# statuses
PROCESSING = "processing"   # started; if seen again the run crashed → quarantine, don't retry
DONE = "done"               # PDF in Cut/, original moved (or move pending)
QUARANTINED = "quarantined" # original in Needs-Review/ (or move pending), Donald told once


class State:
    def __init__(self, path: str = DEFAULT):
        self.path = path
        try:
            with open(path) as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def get(self, fid: str) -> dict | None:
        return self.data.get(fid)

    def put(self, fid: str, **fields) -> dict:
        e = self.data.setdefault(fid, {})
        e.update(fields, updated=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        self.save()
        return e

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def pending_moves(self) -> list[tuple[str, dict]]:
        return [(k, v) for k, v in self.data.items() if v.get("status") in (DONE, QUARANTINED) and not v.get("moved")]
