"""Drive orchestration: poll Receipts/, process each new scan once, file the results,
ping Donald. Failures are quarantined to Needs-Review/ exactly once (no retry storms)."""
from __future__ import annotations

import datetime as dt
import fcntl
import os
import shutil
import subprocess
import time
import traceback

from . import drive, notify, ops, parse, pipeline
from .state import DONE, PROCESSING, QUARANTINED, State

WORK = os.path.expanduser(os.environ.get("RECEIPT_BOT_WORK", "~/receipt-bot-work"))
OUT = os.path.expanduser(os.environ.get("RECEIPT_BOT_OUT", "~/receipts-out"))
LOCK = os.path.expanduser(os.environ.get("RECEIPT_BOT_LOCK", "~/.local/state/receipt-bot/run.lock"))
MAX_DRIVE_ATTEMPTS = 3          # transient Drive errors only; scan/cut errors quarantine at once
MIN_AGE_S = 30                  # let a just-arrived upload settle
DRIVE_DOWN_ALERT_S = 1800       # tell Donald if Drive has been unreachable this long
ALERT = os.path.expanduser("~/bin/uas-alert.sh")


def log(msg: str) -> None:
    print(msg, flush=True)


def acquire_lock():
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    f = open(LOCK, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return None
    return f


def _age_s(item: dict) -> float:
    try:
        t = dt.datetime.fromisoformat(item["ModTime"].replace("Z", "+00:00"))
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds()
    except (KeyError, ValueError):
        return 1e9


def success_line(pdf_name: str) -> str:
    return f"Receipt cut: {pdf_name}"


def attention_line(name: str, reason: str, responder: bool) -> str:
    tail = "Claude is on it" if responder else "auto-responder could not start → needs Donald (file is in Needs-Review)"
    return f"⚠️ Receipt needs attention: {name} — {reason}; {tail}"


def quarantine(st: State, fid: str, name: str, reason: str, dry: bool, workdir: str | None = None) -> None:
    """Needs-Review/ + ONE alert to Donald + hand it to the ops responder. Never retried by the poller."""
    log(f"{name}: QUARANTINE — {reason}")
    if dry:
        return
    e = st.put(fid, status=QUARANTINED, name=name, reason=reason[:500])
    review_name = None
    try:
        drive.ensure_folders()
        review_name = drive.move(name, drive.REVIEW, fid[:8])
        st.put(fid, moved=True, moved_as=review_name)
    except drive.DriveError as ex:
        log(f"{name}: move to Needs-Review failed, will retry the move only: {ex}")
    if not e.get("notified"):
        try:
            pid = ops.enqueue(fid, name, review_name, reason, workdir)
            started = ops.trigger()
            log(f"{name}: queued {pid} for the ops responder (started={started})")
        except OSError as ex:
            log(f"{name}: could not queue for the responder: {ex}")
            started = False
        notify.send(attention_line(name, reason, started), log=log)
        st.put(fid, notified=True, responder=started)


def retry(name: str, dry: bool, vendor: str | None = None, date: dt.date | None = None,
          trim_row=None, search: int | None = None, use_claude: bool = True) -> str:
    """Re-cut a scan sitting in Needs-Review/ (the ops responder's fix path). On success (live):
    PDF → Cut/, original Needs-Review/ → Done/, "Receipt cut: <name>" + PDF to Donald.
    On failure nothing moves. Returns "done" / "dry-run" / "failed: <why>"."""
    st = State()
    fid = next((k for k, v in st.data.items() if isinstance(v, dict) and v.get("moved_as") == name
                and v.get("status") == QUARANTINED), None) or f"manual-{name}"
    wd = os.path.join(WORK, "retry-" + fid[:24])
    shutil.rmtree(wd, ignore_errors=True)
    try:
        local = drive.download("", name, os.path.join(wd, "src"), folder=drive.REVIEW)
        orig = (st.get(fid) or {}).get("name", name)
        res = pipeline.process_file(local, orig, wd, use_claude=use_claude, log=log, vendor=vendor, date=date,
                                    trim_row=trim_row, search=search)
    except (pipeline.ScanError, drive.DriveError) as ex:
        log(f"retry {name}: FAILED — {ex}")
        return f"failed: {ex}"
    os.makedirs(OUT, exist_ok=True)
    shutil.copy2(res.pdf_path, os.path.join(OUT, res.pdf_name))
    if dry:
        log(f"DRY RUN retry OK — would upload {res.pdf_name} to Cut/, move Needs-Review/{name} to Done/, ping: {success_line(res.pdf_name)}")
        return "dry-run"
    drive.ensure_folders()
    cut_name = drive.upload(res.pdf_path, drive.CUT, res.pdf_name, fid[:8])
    done_name = drive.move(name, drive.DONE, fid[:8], src_folder=drive.REVIEW)
    st.put(fid, status=DONE, name=(st.get(fid) or {}).get("name", name), pdf=cut_name, pdf_uploaded=cut_name,
           moved=True, moved_as=done_name, fixed_by="retry", vendor=res.naming.vendor, date=str(res.naming.date),
           checks=res.checks)
    notify.send(success_line(cut_name), attach=res.pdf_path, log=log)
    log(f"retry {name}: done → Cut/{cut_name}, Done/{done_name}")
    shutil.rmtree(wd, ignore_errors=True)
    return "done"


def handle(st: State, item: dict, dry: bool, use_claude: bool = True, force_claude: bool = False) -> str:
    fid, name = item["ID"], item["Name"]
    e = st.get(fid) if not dry else None
    if e:
        if e.get("status") == PROCESSING:
            # a previous run died mid-file (OOM/timeout/crash): count it, don't loop forever
            if e.get("attempts", 0) >= MAX_DRIVE_ATTEMPTS:
                quarantine(st, fid, name, f"bot failed {e.get('attempts')} times on this scan (last: {e.get('last_error', 'crash/timeout')})", dry)
                return "quarantined"
        elif e.get("status") in (DONE, QUARANTINED):
            return "seen"
    attempts = (e or {}).get("attempts", 0) + 1
    if not dry:
        st.put(fid, status=PROCESSING, name=name, attempts=attempts, size=item.get("Size"))
    wd = os.path.join(WORK, fid)
    try:
        if os.path.isdir(wd):
            shutil.rmtree(wd)
        local = drive.download(fid, name, os.path.join(wd, "src"))
        res = pipeline.process_file(local, name, wd, use_claude=use_claude, force_claude=force_claude, log=log)
    except pipeline.ScanError as ex:
        quarantine(st, fid, name, str(ex), dry, wd)
        return "quarantined"
    except drive.DriveError as ex:
        log(f"{name}: Drive error (attempt {attempts}/{MAX_DRIVE_ATTEMPTS}): {ex}")
        if not dry:
            st.put(fid, last_error=str(ex)[:300])
        return "retry"
    except Exception as ex:  # noqa: BLE001 — unexpected = deterministic bug; quarantine once, keep workdir
        log(traceback.format_exc())
        quarantine(st, fid, name, f"internal error {type(ex).__name__}: {str(ex)[:200]}", dry, wd)
        return "quarantined"

    os.makedirs(OUT, exist_ok=True)
    shutil.copy2(res.pdf_path, os.path.join(OUT, res.pdf_name))
    if dry:
        log(f"DRY RUN — would upload {res.pdf_name} to Cut/, move {name} to Done/, and ping: {success_line(res.pdf_name)}")
        return "dry-run"
    st.put(fid, pdf=res.pdf_name, vendor=res.naming.vendor, date=str(res.naming.date),
           sources=res.naming.sources, pages=res.pages, checks=res.checks)
    try:
        drive.ensure_folders()
        cut_name = drive.upload(res.pdf_path, drive.CUT, res.pdf_name, fid[:8])
        st.put(fid, status=DONE, pdf_uploaded=cut_name)
        res.pdf_name = cut_name
        done_name = drive.move(name, drive.DONE, fid[:8])
        st.put(fid, moved=True, moved_as=done_name)
    except drive.DriveError as ex:
        log(f"{name}: Drive filing error: {ex}")
        if not st.get(fid).get("pdf_uploaded"):
            st.put(fid, status=PROCESSING, last_error=str(ex)[:300])
            return "retry"
    notify.send(success_line(res.pdf_name), attach=res.pdf_path, log=log)
    st.put(fid, notified=True)
    shutil.rmtree(wd, ignore_errors=True)
    return "done"


def _drive_health(st: State, ok: bool, err: str = "") -> None:
    meta = st.data.setdefault("_meta", {})
    if ok:
        if meta.pop("drive_down_since", None) and meta.pop("drive_alerted", None):
            subprocess.run([ALERT, "--clear", "receipt-bot-drive", "receipt bot reaches Google Drive again"], timeout=60)
        st.save()
        return
    since = meta.setdefault("drive_down_since", time.time())
    st.save()
    if time.time() - since > DRIVE_DOWN_ALERT_S and not meta.get("drive_alerted"):
        subprocess.run([ALERT, "--key", "receipt-bot-drive",
                        f"receipt bot can't reach Google Drive for {int((time.time() - since) / 60)} min: {err[:200]}"], timeout=60)
        meta["drive_alerted"] = True
        st.save()


def prune_workdirs(days: int = 14) -> None:
    if not os.path.isdir(WORK):
        return
    cutoff = time.time() - days * 86400
    for d in os.listdir(WORK):
        p = os.path.join(WORK, d)
        if os.path.isdir(p) and os.path.getmtime(p) < cutoff:
            shutil.rmtree(p, ignore_errors=True)


def poll(dry: bool = False, use_claude: bool = True, only: str | None = None) -> dict:
    lock = acquire_lock()
    if lock is None:
        log("another run holds the lock — exiting")
        return {}
    st = State()
    counts: dict[str, int] = {}
    try:
        items = drive.list_incoming()
        if drive.duplicate_names(items) and not dry:
            log(f"duplicate names in Receipts/: {drive.duplicate_names(items)} — rclone dedupe rename")
            drive.dedupe_rename()
            items = drive.list_incoming()
    except (drive.DriveError, subprocess.TimeoutExpired) as ex:
        log(f"listing failed: {ex}")
        if not dry:
            _drive_health(st, False, str(ex))
        return {"drive-error": 1}
    if not dry:
        _drive_health(st, True)

    if not dry:  # finish any half-filed results (move retries only — never reprocess)
        present = {i["ID"] for i in items}
        for fid, e in st.pending_moves():
            if fid in present:
                folder = drive.DONE if e["status"] == DONE else drive.REVIEW
                try:
                    st.put(fid, moved=True, moved_as=drive.move(e["name"], folder, fid[:8]))
                    log(f"{e['name']}: pending move to {folder} completed")
                except drive.DriveError as ex:
                    log(f"{e['name']}: pending move still failing: {ex}")
            else:
                st.put(fid, moved=True, moved_as="(gone from Receipts/)")

    for it in items:
        if not parse.is_receipt_file(it["Name"]) or (only and it["Name"] != only):
            continue
        if _age_s(it) < MIN_AGE_S:
            log(f"{it['Name']}: just arrived, next run")
            continue
        r = handle(st, it, dry, use_claude=use_claude)
        counts[r] = counts.get(r, 0) + 1
    if not dry:
        prune_workdirs()
    log(f"poll: {len(items)} file(s) in Receipts/ → {counts or 'nothing new'}")
    return counts
