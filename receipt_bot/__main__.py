"""receipt-bot CLI.

  python -m receipt_bot poll [--dry-run] [--no-claude] [--only NAME]
      One pass over gdrive:ScanSnap/Receipts/ (what the systemd timer runs every 2 min).
  python -m receipt_bot process FILE [--name NAME] [--dry-run] [--no-claude] [--force-claude] [--out DIR]
      FILE is a local path, or drive:NAME for a scan in Receipts/.
      Local file: read + trim + cut + verify, PDF written to --out (default ~/receipts-out).
      drive:NAME without --dry-run: the full live flow for that one scan (Cut/, Done/, Discord).
      --dry-run: no Drive moves/uploads, no Discord, no state writes.
  python -m receipt_bot retry NAME [--dry-run] [--vendor V --date YYYY-MM-DD] [--trim-row N | --no-trim] [--search-range PX]
      Re-cut a scan from Receipts/Needs-Review/ with overrides; live success files it like a normal cut.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys
import tempfile

from . import bot, drive, pipeline


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="receipt-bot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("poll")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-claude", action="store_true")
    p.add_argument("--only")
    q = sub.add_parser("process")
    q.add_argument("file")
    q.add_argument("--name", help="treat the file as having this scan name (for the filename date/vendor)")
    q.add_argument("--dry-run", action="store_true")
    q.add_argument("--no-claude", action="store_true")
    q.add_argument("--force-claude", action="store_true", help="test the Claude fallback even when OCR succeeds")
    q.add_argument("--out", default=bot.OUT)
    r = sub.add_parser("retry", help="re-cut a scan in Needs-Review/ (ops responder fix path)")
    r.add_argument("name", help="file name inside Receipts/Needs-Review/")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--vendor")
    r.add_argument("--date", help="YYYY-MM-DD")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--trim-row", type=int, help="keep scan rows [0:N) instead of the vendor trim rule")
    g.add_argument("--no-trim", action="store_true")
    r.add_argument("--search-range", type=int, help="px a cut may move to find whitespace (default 225)")
    r.add_argument("--no-claude", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "retry":
        lock = bot.acquire_lock()
        if lock is None:
            print("the poller is running — try again in a minute", file=sys.stderr)
            return 3
        d = dt.date.fromisoformat(a.date) if a.date else None
        res = bot.retry(a.name, a.dry_run, vendor=a.vendor, date=d,
                        trim_row="none" if a.no_trim else a.trim_row, search=a.search_range, use_claude=not a.no_claude)
        print(f"result: {res}")
        return 0 if res in ("done", "dry-run") else 1

    if a.cmd == "poll":
        c = bot.poll(dry=a.dry_run, use_claude=not a.no_claude, only=a.only)
        return 1 if "drive-error" in c else 0

    if a.file.startswith("drive:"):
        name = a.file[len("drive:"):]
        items = [i for i in drive.list_incoming() if i["Name"] == name]
        if not items:
            print(f"{name} is not in {drive.ROOT}/", file=sys.stderr)
            return 2
        lock = bot.acquire_lock() if not a.dry_run else True
        if lock is None:
            print("the poller is running — try again in a minute", file=sys.stderr)
            return 3
        r = bot.handle(bot.State(), items[0], a.dry_run, use_claude=not a.no_claude, force_claude=a.force_claude)
        print(f"result: {r}")
        return 0 if r in ("done", "dry-run") else 1

    name = a.name or os.path.basename(a.file)
    wd = tempfile.mkdtemp(prefix="receipt-", dir=os.environ.get("TMPDIR"))
    try:
        res = pipeline.process_file(a.file, name, wd, use_claude=not a.no_claude, force_claude=a.force_claude, log=print)
    except pipeline.ScanError as ex:
        print(f"NEEDS REVIEW: {ex}")
        return 1
    os.makedirs(a.out, exist_ok=True)
    dest = os.path.join(a.out, res.pdf_name)
    shutil.copy2(res.pdf_path, dest)
    print(f"{bot.success_line(res.pdf_name)}  →  {dest}")
    if not a.dry_run:
        print("(local file: nothing is uploaded or pinged; use drive:NAME for the live flow)")
    shutil.rmtree(wd, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
