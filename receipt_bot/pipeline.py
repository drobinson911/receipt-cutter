"""One receipt, the manual procedure automated: read just enough to name it (store, date) →
vendor trim rule → cut → check nothing was sliced or dropped. No Drive, no Discord (bot.py)."""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from . import claude_fallback, ocr, parse, vendors, verify

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cut_receipt  # noqa: E402

Image.MAX_IMAGE_PIXELS = 400_000_000  # a 68-inch simplex receipt at 300 dpi is ~20k rows


class ScanError(Exception):
    """The scan can't be turned into a good PDF: quarantine it (no retry)."""


@dataclass
class Naming:
    vendor: str | None = None
    date: dt.date | None = None
    sources: dict = field(default_factory=dict)   # "vendor"/"date" → ocr / filename / claude


@dataclass
class Result:
    naming: Naming
    pdf_path: str
    pdf_name: str
    pages: int
    geometry: dict
    checks: dict
    trim_note: str | None


def load_image(path: str, workdir: str) -> Image.Image:
    if path.lower().endswith(".pdf"):
        prefix = os.path.join(workdir, "pdfpage")
        r = subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", path, prefix], capture_output=True, timeout=300)
        pages = sorted(f for f in os.listdir(workdir) if f.startswith("pdfpage") and f.endswith(".png"))
        if r.returncode != 0 or not pages:
            raise ScanError("PDF could not be rasterised")
        ims = [Image.open(os.path.join(workdir, p)).convert("L") for p in pages]
        out = Image.new("L", (max(i.width for i in ims), sum(i.height for i in ims)), 255)
        y = 0
        for i in ims:
            out.paste(i, (0, y)); y += i.height
        return out
    try:
        img = Image.open(path)
        img.load()
    except Exception as e:  # noqa: BLE001
        raise ScanError(f"image can't be opened ({type(e).__name__})") from e
    return img.convert("L")


def check_image(img: Image.Image) -> None:
    a = np.asarray(img)
    if img.width < 200 or img.height < 200:
        raise ScanError(f"image too small ({img.width}x{img.height})")
    std, mean = float(a.std()), float(a.mean())
    if std < 1.0:
        kind = "all-black" if mean < 128 else "blank"
        raise ScanError(f"{kind} image (std dev {std:.1f}): the export bug, not a receipt; rescan it")
    if (a < cut_receipt.INK_LEVEL).sum() < 500:
        raise ScanError("no text on the scan (nearly blank)")


def read_naming(img: Image.Image, filename: str, workdir: str, lines, spans, use_claude: bool = True,
                force_claude: bool = False, today: dt.date | None = None, log=print) -> Naming:
    sn = parse.parse_scan_filename(filename)
    texts = [l.text for l in lines]
    n = Naming()
    v = vendors.detect(texts)
    if v:
        n.vendor, n.sources["vendor"] = v.name, "ocr"
    elif sn.vendor:
        fv = vendors.by_name(sn.vendor)
        n.vendor, n.sources["vendor"] = (fv.name if fv else sn.vendor), "filename"
    d, src = parse.choose_date(parse.find_dates("\n".join(texts), today), sn.date)
    if d:
        n.date, n.sources["date"] = d, src

    missing = ["vendor", "date"] if force_claude else [f for f in ("vendor", "date") if getattr(n, f) is None]
    if use_claude and missing:
        # store + date are printed in the header: send just the first two strips
        sdir = os.path.join(workdir, "strips"); os.makedirs(sdir, exist_ok=True)
        imgs = []
        for i, (a, b) in enumerate(spans[:2]):
            p = os.path.join(sdir, f"strip{i:02d}.png"); img.crop((0, a, img.width, b)).save(p); imgs.append(p)
        ans = claude_fallback.ask(imgs, missing, workdir, log=log)
        if "vendor" in missing and ans.get("vendor"):
            kv = vendors.by_name(str(ans["vendor"]))
            n.vendor, n.sources["vendor"] = (kv.name if kv else str(ans["vendor"])), "claude"
        if "date" in missing and ans.get("date"):
            ds = parse.find_dates(str(ans["date"]), today)
            if ds:
                n.date, n.sources["date"] = ds[0], "claude"
    return n


def search_range() -> int:
    return int(os.environ.get("RECEIPT_BOT_SEARCH_RANGE", cut_receipt.SEARCH_RANGE))


def process_file(path: str, filename: str, workdir: str, use_claude: bool = True, force_claude: bool = False,
                 today: dt.date | None = None, log=print, vendor: str | None = None, date: dt.date | None = None,
                 trim_row: int | str | None = None, search: int | None = None) -> Result:
    """vendor/date/trim_row/search are manual overrides (the ops responder's retry):
    trim_row=None → vendor rule, "none" → no trim, int → keep rows [0:trim_row)."""
    os.makedirs(workdir, exist_ok=True)
    img = load_image(path, workdir)
    check_image(img)
    log(f"{filename}: {img.width}x{img.height}")
    lines, spans = ocr.ocr_lines(img)
    if vendor and date:
        n = Naming(vendor, date, {"vendor": "manual", "date": "manual"})
    else:
        n = read_naming(img, filename, workdir, lines, spans, use_claude, force_claude, today, log)
        if vendor:
            n.vendor, n.sources["vendor"] = vendor, "manual"
        if date:
            n.date, n.sources["date"] = date, "manual"
    log(f"{filename}: store={n.vendor} date={n.date} sources={n.sources}")
    if not n.vendor:
        raise ScanError("couldn't read the store name")
    if not n.date:
        raise ScanError("couldn't read the receipt date")

    trim_note = None
    trim = vendors.select_trim(n.vendor)
    if trim_row == "none":
        trim_note = "trim skipped (manual override)"
    elif isinstance(trim_row, int):
        if not 0 < trim_row <= img.height:
            raise ScanError(f"trim row {trim_row} outside the scan (height {img.height})")
        trim_note = f"trimmed at row {trim_row} (manual override)"
        img = img.crop((0, 0, img.width, trim_row))
    elif trim:
        a = np.asarray(img)
        row, trim_note = trim(a, ocr.ink_profile(a), lines)
        log(trim_note)
        if row:
            img = img.crop((0, 0, img.width, row))

    pdf_name = parse.output_pdf_name(n.date, n.vendor)
    pdf_path = os.path.join(workdir, pdf_name)
    geom = cut_receipt.cut(img, pdf_path, log=log, search=search if search is not None else search_range())
    try:
        verify.check_sliced(geom, pdf_path)
        checks = verify.check_dropped(img, geom, pdf_path, workdir)
    except verify.CutCheckError as e:
        raise ScanError(f"cut check failed: {e}") from e
    log(f"{pdf_name}: {geom['pages']} page(s); 0 ink on all {len(geom['ink_on_cuts'])} cut rows; "
        f"nothing dropped ({checks['lines_scan']} text lines in scan = {checks['lines_pdf']} in PDF, "
        f"ink rows {checks['ink_rows_scan']}/{checks['ink_rows_pdf']})")
    return Result(n, pdf_path, pdf_name, geom["pages"], geom, checks, trim_note)
