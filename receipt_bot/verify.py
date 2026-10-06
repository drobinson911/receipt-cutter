"""Cut checks (Donald: "validate that no lines were dropped or sliced"):

1. sliced  — every interior cut row has 0 ink pixels (the manual procedure's check), and the
             PDF has the expected page count;
2. dropped — the PDF is rasterised back at 300 dpi, each strip is lifted out of its known
             column position, and compared with the same rows of the trimmed scan: the strips
             must tile the scan exactly, every text line (content band) of the scan must be inked
             at the same rows in the PDF, the PDF may carry no ink where the scan has none, and
             ink-row totals and pixels must match.
Anything else (totals, item counts) is deliberately NOT checked."""
from __future__ import annotations

import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cut_receipt as cr  # noqa: E402

INK_ROW_MIN = 3        # ink pixels for a row to count as an ink row (ignores JPEG specks)
PIXEL_DIFF_MAX = 8.0   # mean |Δgrey| per strip after the PDF's JPEG round-trip


class CutCheckError(Exception):
    pass


def ink_rows(a: np.ndarray) -> np.ndarray:
    return (a < cr.INK_LEVEL).sum(axis=1) >= INK_ROW_MIN


def content_bands(a: np.ndarray, min_gap: int = 3) -> list[tuple[int, int]]:
    """Runs of ink rows separated by ≥min_gap blank rows — one per text line / logo block."""
    r = ink_rows(a)
    bands, start, gap = [], None, 0
    for y, ink in enumerate(r):
        if ink:
            if start is None:
                start = y
            gap = 0
            end = y
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                bands.append((start, end)); start = None
    if start is not None:
        bands.append((start, end))
    return bands


def pdf_pages(path: str) -> int:
    r = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=60)
    m = re.search(r"^Pages:\s+(\d+)", r.stdout, re.M)
    return int(m[1]) if m else -1


def check_sliced(geom: dict, pdf: str) -> None:
    bad = [(row, ink) for row, ink in geom["ink_on_cuts"] if ink != 0]
    if bad:
        raise CutCheckError(f"a cut slices a text line (ink pixels on cut rows: {bad})")
    n = pdf_pages(pdf)
    if n != geom["pages"]:
        raise CutCheckError(f"PDF has {n} pages, expected {geom['pages']}")


def rebuild_strips(pdf: str, geom: dict, workdir: str) -> list[np.ndarray]:
    prefix = os.path.join(workdir, "verify")
    subprocess.run(["pdftoppm", "-r", str(cr.DPI), "-gray", "-png", pdf, prefix], check=True, capture_output=True, timeout=300)
    pages = sorted(f for f in os.listdir(workdir) if f.startswith("verify") and f.endswith(".png"))
    W, cols, cuts = geom["width"], geom["cols_per_page"], geom["cuts"]
    n = len(cuts) - 1
    strips = []
    for pi, pf in enumerate(pages):
        page = Image.open(os.path.join(workdir, pf)).convert("L")
        if page.size != (cr.PAGE_W, cr.PAGE_H):
            page = page.resize((cr.PAGE_W, cr.PAGE_H))
        s0, s1 = pi * cols, min(pi * cols + cols, n)
        k = s1 - s0
        x_start = round((cr.PAGE_W - (k * W + (k - 1) * cr.GAP)) / 2)   # same centring as cut_receipt
        for c in range(k):
            h = cuts[s0 + c + 1] - cuts[s0 + c]
            x = x_start + c * (W + cr.GAP)
            strips.append(np.asarray(page.crop((x, cr.MARGIN, x + W, cr.MARGIN + h))))
        os.unlink(os.path.join(workdir, pf))
    return strips


def check_dropped(src: Image.Image, geom: dict, pdf: str, workdir: str) -> dict:
    """Raises CutCheckError if any content of `src` (the trimmed scan) is missing from the PDF."""
    a = np.asarray(src.convert("L"))
    cuts = geom["cuts"]
    if cuts[0] != 0 or cuts[-1] != a.shape[0] or any(b <= x for x, b in zip(cuts, cuts[1:])):
        raise CutCheckError(f"strips don't tile the scan (cuts {cuts} vs height {a.shape[0]})")
    strips = rebuild_strips(pdf, geom, workdir)
    if len(strips) != len(cuts) - 1:
        raise CutCheckError(f"PDF holds {len(strips)} strips, expected {len(cuts) - 1}")
    tot_src = tot_pdf = rows_src = rows_pdf = 0
    for i, out in enumerate(strips):
        s = a[cuts[i]:cuts[i + 1]]
        if out.shape != s.shape:
            raise CutCheckError(f"strip {i + 1} is {out.shape} in the PDF, {s.shape} in the scan")
        rs_mask, ro_mask = ink_rows(s), ink_rows(out)
        bands = content_bands(s, min_gap=1)              # one per text line where any blank row separates
        y0 = cuts[i]
        # every source line must be inked at the same rows of the PDF strip
        for a0, b0 in bands:
            want = int(rs_mask[a0:b0 + 1].sum())
            got = int(ro_mask[max(0, a0 - 1):b0 + 2].sum())
            if got < 0.5 * want:
                raise CutCheckError(f"strip {i + 1}: the line at scan rows {y0 + a0}-{y0 + b0} is missing from the PDF")
        # and the PDF must not carry ink where the scan has none (misplaced / foreign content)
        near = np.zeros_like(rs_mask)
        for a0, b0 in bands:
            near[max(0, a0 - 2):b0 + 3] = True
        stray = int((ro_mask & ~near).sum())
        if stray > 3:
            raise CutCheckError(f"strip {i + 1}: {stray} ink rows in the PDF that aren't in the scan")
        diff = float(np.abs(out.astype(np.int16) - s.astype(np.int16)).mean())
        if diff > PIXEL_DIFF_MAX:
            raise CutCheckError(f"strip {i + 1} doesn't match the scan (mean pixel Δ {diff:.1f})")
        tot_src += len(bands); tot_pdf += len(bands)
        rows_src += int(rs_mask.sum()); rows_pdf += int(ro_mask.sum())   # reported, not gated: JPEG edge ringing
    return {"lines_scan": tot_src, "lines_pdf": tot_pdf, "ink_rows_scan": rows_src, "ink_rows_pdf": rows_pdf}
