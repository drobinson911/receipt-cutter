"""The real ScanSnap receipt (10062026.jpg, FoodMaxx), end to end through the CLI in --dry-run."""
import os
import re
import subprocess
import sys

import pytest

from conftest import REAL_FIXTURE, ROOT

pytestmark = pytest.mark.skipif(not os.path.exists(REAL_FIXTURE), reason="real receipt fixture not on this machine")


def _run(tmp_path, *extra, env=None):
    e = dict(os.environ, RECEIPT_BOT_NO_DISCORD="1", RECEIPT_BOT_NO_TRIGGER="1", TMPDIR=str(tmp_path), **(env or {}))
    return subprocess.run([sys.executable, "-m", "receipt_bot", "process", REAL_FIXTURE, "--dry-run", "--no-claude",
                           "--out", str(tmp_path / "out"), *extra], cwd=ROOT, env=e, capture_output=True, text=True, timeout=600)


def test_real_receipt_dry_run(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "store=FoodMaxx date=2026-10-06" in out
    assert "FoodMaxx footer trimmed at row" in out
    pdf = tmp_path / "out" / "20261006_Robinson_FoodMaxx.pdf"
    assert pdf.exists()
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    assert re.search(r"^Pages:\s+2$", info, re.M) and "612 x 792" in info          # 2 letter pages
    cuts = re.search(r"ink pixels on each interior cut row \(must be 0\): (\[.*\])", out)[1]
    assert re.findall(r"\(\d+, (\d+)\)", cuts) == ["0", "0", "0"]
    m = re.search(r"nothing dropped \((\d+) text lines in scan = (\d+) in PDF", out)
    assert m and m[1] == m[2] and int(m[1]) > 150
    assert "Receipt cut: 20261006_Robinson_FoodMaxx.pdf" in out


def test_real_receipt_forced_slice_goes_to_review(tmp_path):
    r = _run(tmp_path, env={"RECEIPT_BOT_SEARCH_RANGE": "0"})
    assert r.returncode == 1
    assert "NEEDS REVIEW: cut check failed: a cut slices a text line" in r.stdout
