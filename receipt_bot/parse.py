"""Pure text parsing: scan filenames, output names, receipt dates.
Works on plain strings so it is unit-testable without tesseract, Drive or Discord."""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from dataclasses import dataclass

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".pdf"}

# ScanSnap Cloud title "[Date on a receipt]_[Vendor]" → MMDDYYYY_Vendor.jpg, and very
# often just MMDDYYYY.jpg (vendor not detected). rclone dedupe may add "-1".
_FN = re.compile(r"^(?P<mm>\d{2})(?P<dd>\d{2})(?P<yyyy>\d{4})(?:[_ -]+(?P<vendor>.*?))?(?:\s*\(\d+\)|-\d+)?$")


@dataclass
class ScanName:
    date: dt.date | None
    vendor: str | None
    ext: str


def parse_scan_filename(name: str) -> ScanName:
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    ext = "." + ext.lower() if ext else ""
    m = _FN.match(stem.strip())
    if not m:
        return ScanName(None, None, ext)
    try:
        d = dt.date(int(m["yyyy"]), int(m["mm"]), int(m["dd"]))
    except ValueError:
        d = None
    v = (m["vendor"] or "").strip(" _-") or None
    if v and v.isdigit():
        v = None
    return ScanName(d, v, ext)


def is_receipt_file(name: str) -> bool:
    n = name.lower()
    return any(n.endswith(e) for e in IMAGE_EXTS) and not n.startswith(".")


def store_slug(vendor: str) -> str:
    """'Food Maxx #474' → 'FoodMaxx'; keeps existing CamelCase, drops punctuation/store numbers."""
    v = re.sub(r"#\s*\d+", " ", vendor)
    v = v.replace("&", " and ").replace("'", "")
    words = [w for w in re.split(r"[^A-Za-z0-9]+", v) if w]
    out = "".join(w if (w[0].isupper() and not w.isupper()) or w.isdigit() else w.capitalize() for w in words)
    return out[:40] or "Unknown"


def output_pdf_name(date: dt.date, vendor: str) -> str:
    return f"{date:%Y%m%d}_Robinson_{store_slug(vendor)}.pdf"


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_D_NUM = re.compile(r"(?<![\d/])(\d{1,2})\s?[/-]\s?(\d{1,2})\s?[/-]\s?(\d{4}|\d{2})(?![\d/])")
_D_ISO = re.compile(r"(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)")
_D_TXT = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})\b", re.I)


def _mk(y: int, m: int, d: int) -> dt.date | None:
    if y < 100:
        y += 2000
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str, today: dt.date | None = None) -> list[dt.date]:
    """All plausible dates (within 3 years back .. tomorrow), in text order."""
    today = today or dt.date.today()
    lo, hi = today - dt.timedelta(days=3 * 366), today + dt.timedelta(days=1)
    found: list[tuple[int, dt.date]] = []
    for m in _D_NUM.finditer(text):
        d = _mk(int(m[3]), int(m[1]), int(m[2]))
        if d:
            found.append((m.start(), d))
    for m in _D_ISO.finditer(text):
        d = _mk(int(m[1]), int(m[2]), int(m[3]))
        if d:
            found.append((m.start(), d))
    for m in _D_TXT.finditer(text):
        d = _mk(int(m[3]), _MONTHS[m[1].lower()[:3]], int(m[2]))
        if d:
            found.append((m.start(), d))
    return [d for _, d in sorted(found, key=lambda t: t[0]) if lo <= d <= hi]


def choose_date(ocr_dates: list[dt.date], filename_date: dt.date | None) -> tuple[dt.date | None, str]:
    """The receipt's printed date wins; ScanSnap's filename date (its own OCR) confirms or fills in."""
    if filename_date and filename_date in ocr_dates:
        return filename_date, "ocr+filename"
    if ocr_dates:
        best, _ = Counter(ocr_dates).most_common(1)[0]
        return best, "ocr"
    if filename_date:
        return filename_date, "filename"
    return None, "none"
