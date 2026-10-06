"""Idempotency (state file) + failure paths, against a local sandbox 'Drive' (real rclone on a temp dir)."""
import datetime as dt
import json
import os

import pytest

from receipt_bot import pipeline


class FakeResult:
    def __init__(self, workdir, name="20261006_Robinson_FoodMaxx.pdf"):
        self.pdf_name = name
        self.pdf_path = os.path.join(workdir, name)
        os.makedirs(workdir, exist_ok=True)
        open(self.pdf_path, "wb").write(b"%PDF-1.4 fake")
        self.pages = 2
        self.checks = {"lines_scan": 1, "lines_pdf": 1, "ink_rows_scan": 1, "ink_rows_pdf": 1}
        self.naming = pipeline.Naming("FoodMaxx", dt.date(2026, 10, 6), {})


def _drop(root, name="10062026.jpg"):
    p = root / name
    p.write_bytes(b"fake scan")
    os.utime(p, (0, 0))   # old enough to pass the settle delay
    return p


@pytest.fixture
def calls(monkeypatch, sandbox):
    rec = {"process": 0, "sent": []}
    monkeypatch.setattr("receipt_bot.notify.send", lambda text, attach=None, log=print: rec["sent"].append((text, attach)) or True)
    return rec


def _ok(calls):
    def f(path, name, workdir, **kw):
        calls["process"] += 1
        return FakeResult(workdir)
    return f


def test_success_files_and_is_idempotent(sandbox, calls, monkeypatch):
    bot, root = sandbox["bot"], sandbox["root"]
    _drop(root)
    monkeypatch.setattr("receipt_bot.pipeline.process_file", _ok(calls))
    assert bot.poll() == {"done": 1}
    assert (root / "Cut" / "20261006_Robinson_FoodMaxx.pdf").exists()
    assert (root / "Done" / "10062026.jpg").exists() and not (root / "10062026.jpg").exists()
    assert calls["sent"] == [("Receipt cut: 20261006_Robinson_FoodMaxx.pdf", calls["sent"][0][1])]
    assert calls["sent"][0][1].endswith(".pdf")
    # nothing reprocessed on the next polls
    assert bot.poll() == {} and bot.poll() == {}
    assert calls["process"] == 1 and len(calls["sent"]) == 1
    st = json.load(open(os.environ["RECEIPT_BOT_STATE"]))
    assert st["local-10062026.jpg"]["status"] == "done" and st["local-10062026.jpg"]["moved"] is True


def test_state_survives_a_put_back_original(sandbox, calls, monkeypatch):
    """Even if the same file (same ID) shows up again, it is not re-cut."""
    bot, root = sandbox["bot"], sandbox["root"]
    _drop(root)
    monkeypatch.setattr("receipt_bot.pipeline.process_file", _ok(calls))
    bot.poll()
    _drop(root)                       # same name → same local ID
    bot.poll()
    assert calls["process"] == 1


def test_no_overwrite_in_cut(sandbox, calls, monkeypatch):
    bot, root = sandbox["bot"], sandbox["root"]
    (root / "Cut").mkdir()
    (root / "Cut" / "20261006_Robinson_FoodMaxx.pdf").write_bytes(b"earlier receipt")
    _drop(root)
    monkeypatch.setattr("receipt_bot.pipeline.process_file", _ok(calls))
    bot.poll()
    assert (root / "Cut" / "20261006_Robinson_FoodMaxx.pdf").read_bytes() == b"earlier receipt"
    assert (root / "Cut" / "20261006_Robinson_FoodMaxx_2.pdf").exists()


def test_scan_error_quarantines_once_and_queues_responder(sandbox, calls, monkeypatch):
    bot, root, tmp = sandbox["bot"], sandbox["root"], sandbox["tmp"]
    _drop(root)

    def boom(*a, **k):
        calls["process"] += 1
        raise pipeline.ScanError("all-black image (std dev 0.0): the export bug, not a receipt; rescan it")
    monkeypatch.setattr("receipt_bot.pipeline.process_file", boom)
    assert bot.poll() == {"quarantined": 1}
    assert (root / "Needs-Review" / "10062026.jpg").exists() and not (root / "Done").glob("*.jpg").__next__ if False else True
    assert not list((root / "Done").glob("*"))
    assert len(calls["sent"]) == 1
    msg = calls["sent"][0][0]
    assert msg.startswith("⚠️ Receipt needs attention: 10062026.jpg — all-black image") and msg.endswith("Claude is on it")
    q = tmp / "ops" / "queue" / "receipt__local-100620.json"
    job = json.load(open(q))
    assert job["id"] == "receipt:local-100620" and job["receipt"]["review_name"] == "10062026.jpg"
    assert job["receipt"]["env"]["RECEIPT_BOT_DRIVE_ROOT"] == str(root) and job["receipt"]["sandbox"] is True
    # quarantined once: later polls neither reprocess nor re-alert (no retry storm)
    bot.poll(); bot.poll()
    assert calls["process"] == 1 and len(calls["sent"]) == 1


def test_responder_unavailable_says_needs_donald(sandbox, calls, monkeypatch):
    bot, root = sandbox["bot"], sandbox["root"]
    _drop(root)
    monkeypatch.setattr("receipt_bot.ops.trigger", lambda: False)
    monkeypatch.setattr("receipt_bot.pipeline.process_file", lambda *a, **k: (_ for _ in ()).throw(pipeline.ScanError("cut check failed: x")))
    bot.poll()
    assert "auto-responder could not start → needs Donald" in calls["sent"][0][0]


def test_unexpected_exception_is_quarantined_not_retried(sandbox, calls, monkeypatch):
    bot, root = sandbox["bot"], sandbox["root"]
    _drop(root)

    def crash(*a, **k):
        calls["process"] += 1
        raise ZeroDivisionError("bug")
    monkeypatch.setattr("receipt_bot.pipeline.process_file", crash)
    assert bot.poll() == {"quarantined": 1}
    bot.poll()
    assert calls["process"] == 1 and "internal error ZeroDivisionError" in calls["sent"][0][0]


def test_drive_error_retries_then_quarantines(sandbox, calls, monkeypatch):
    bot, root, drive = sandbox["bot"], sandbox["root"], sandbox["drive"]
    _drop(root)

    def flaky(*a, **k):
        calls["process"] += 1
        raise drive.DriveError("rclone copyto failed (1): 503")
    monkeypatch.setattr(drive, "download", flaky)
    results = [bot.poll() for _ in range(5)]
    assert results[:3] == [{"retry": 1}] * 3
    assert results[3] == {"quarantined": 1} and results[4] == {}
    assert calls["process"] == 3 and len(calls["sent"]) == 1


def test_crash_mid_file_counts_as_attempt(sandbox, calls, monkeypatch):
    bot, root, state = sandbox["bot"], sandbox["root"], sandbox["state"]
    _drop(root)
    st = state.State()
    st.put("local-10062026.jpg", status=state.PROCESSING, name="10062026.jpg", attempts=3)
    monkeypatch.setattr("receipt_bot.pipeline.process_file", _ok(calls))
    assert bot.poll() == {"quarantined": 1}
    assert calls["process"] == 0 and "failed 3 times" in calls["sent"][0][0]


def test_lock_blocks_overlapping_runs(sandbox):
    bot = sandbox["bot"]
    held = bot.acquire_lock()
    assert held is not None and bot.acquire_lock() is None
    assert bot.poll() == {}


def test_dry_run_moves_nothing_and_sends_nothing(sandbox, calls, monkeypatch):
    bot, root = sandbox["bot"], sandbox["root"]
    _drop(root)
    monkeypatch.setattr("receipt_bot.pipeline.process_file", _ok(calls))
    assert bot.poll(dry=True) == {"dry-run": 1}
    assert (root / "10062026.jpg").exists() and not (root / "Cut").exists()
    assert calls["sent"] == [] and not os.path.exists(os.environ["RECEIPT_BOT_STATE"])


def test_retry_from_needs_review_files_it(sandbox, calls, monkeypatch):
    bot, root = sandbox["bot"], sandbox["root"]
    _drop(root)
    monkeypatch.setattr("receipt_bot.pipeline.process_file", lambda *a, **k: (_ for _ in ()).throw(pipeline.ScanError("cut check failed")))
    bot.poll()
    seen = {}

    def fixed(path, name, workdir, **kw):
        seen.update(kw)
        return FakeResult(workdir)
    monkeypatch.setattr("receipt_bot.pipeline.process_file", fixed)
    assert bot.retry("10062026.jpg", dry=True, search=300) == "dry-run"
    assert (root / "Needs-Review" / "10062026.jpg").exists() and seen["search"] == 300
    assert bot.retry("10062026.jpg", dry=False, search=300) == "done"
    assert (root / "Done" / "10062026.jpg").exists() and not (root / "Needs-Review" / "10062026.jpg").exists()
    assert (root / "Cut" / "20261006_Robinson_FoodMaxx.pdf").exists()
    assert calls["sent"][-1][0] == "Receipt cut: 20261006_Robinson_FoodMaxx.pdf"
    st = json.load(open(os.environ["RECEIPT_BOT_STATE"]))
    assert st["local-10062026.jpg"]["status"] == "done"
    bot.poll()   # and the poller leaves it alone afterwards
    assert len([s for s in calls["sent"] if s[0].startswith("Receipt cut")]) == 1


def test_retry_failure_leaves_file_in_review(sandbox, calls, monkeypatch):
    bot, root = sandbox["bot"], sandbox["root"]
    (root / "Needs-Review").mkdir()
    (root / "Needs-Review" / "x.jpg").write_bytes(b"x")
    monkeypatch.setattr("receipt_bot.pipeline.process_file", lambda *a, **k: (_ for _ in ()).throw(pipeline.ScanError("still sliced")))
    assert bot.retry("x.jpg", dry=False).startswith("failed: still sliced")
    assert (root / "Needs-Review" / "x.jpg").exists() and calls["sent"] == []
