"""Hand a failed receipt to forge's ops first responder (~/bin/uas-ops-responder.sh), the same
way the pipeline watchdog does: a job JSON in ~/uas-ops/queue/ + start uas-ops-responder.service.
The responder follows the "Receipts" playbook in ~/uas-ops/RESPONDER.md."""
from __future__ import annotations

import json
import os
import subprocess
import time

OPS = os.path.expanduser(os.environ.get("UAS_OPS_DIR", "~/uas-ops"))
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# env the responder must reuse so its retry acts on the same Drive root / state (sandbox tests)
_PASS_ENV = ("RECEIPT_BOT_DRIVE_ROOT", "RECEIPT_BOT_STATE", "RECEIPT_BOT_WORK", "RECEIPT_BOT_OUT",
             "RECEIPT_BOT_LOCK", "RECEIPT_BOT_NO_DISCORD", "RECEIPT_BOT_SEARCH_RANGE", "UAS_OPS_DIR")


def problem_id(fid: str) -> str:
    return f"receipt:{fid[:12]}"


def enqueue(fid: str, name: str, review_name: str | None, reason: str, workdir: str | None) -> str:
    """Write ~/uas-ops/queue/receipt__<id>.json (atomic). Returns the problem id."""
    pid = problem_id(fid)
    env = {k: os.environ[k] for k in _PASS_ENV if os.environ.get(k)}
    sandbox = bool(env.get("RECEIPT_BOT_DRIVE_ROOT"))
    where = f"{env.get('RECEIPT_BOT_DRIVE_ROOT', 'gdrive:ScanSnap/Receipts')}/Needs-Review/{review_name or name}"
    py = f"{REPO}/.venv/bin/python -m receipt_bot"
    rec = {
        "id": pid,
        "desc": f"receipt {name} failed to cut: {reason}"[:300],
        "evidence": (f"scan now at {where}" + ("" if review_name else " (move to Needs-Review still pending)")
                     + f"; workdir {workdir or '-'}; bot log: journalctl --user -u receipt-bot.service --since -1h"
                     + "; state: " + os.environ.get("RECEIPT_BOT_STATE", "~/.local/state/receipt-bot/state.json")),
        "playbook": (f"Receipts playbook in RESPONDER.md. Dry-run first: cd {REPO} && {py} retry '{review_name or name}' --dry-run "
                     "[--vendor V --date YYYY-MM-DD] [--trim-row N | --no-trim] [--search-range PX]; when that passes, "
                     "the same command without --dry-run files it (Cut/, Done/, PDF to Donald)."),
        "receipt": {"file_id": fid, "name": name, "review_name": review_name or name, "reason": reason,
                    "workdir": workdir, "repo": REPO, "env": env, "sandbox": sandbox},
        "queued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "first_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    os.makedirs(os.path.join(OPS, "queue"), exist_ok=True)
    q = os.path.join(OPS, "queue", pid.replace(":", "__") + ".json")
    tmp = q + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=1)
    os.replace(tmp, q)
    return pid


def trigger() -> bool:
    """Start the responder now (same call the watchdog makes). False if it can't be started."""
    if os.environ.get("RECEIPT_BOT_NO_TRIGGER"):
        return True
    env = dict(os.environ)
    uid = os.getuid()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    try:
        r = subprocess.run(["systemctl", "--user", "start", "--no-block", "uas-ops-responder.service"],
                           env=env, capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
