"""Vendor recognition and per-vendor trim rules.

A vendor is recognised from the OCR text of the receipt (header first) or from the
ScanSnap filename. A trim rule returns the row to crop the scan at (keep [0:row)),
or None for "no trim"."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import numpy as np



@dataclass
class Vendor:
    name: str                 # canonical display name; the PDF slug is parse.store_slug(name)
    patterns: list[str]       # regexes over normalised OCR text (lowercase, no spaces)
    trim: Callable | None = None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9&]", "", s.lower())


# ── trim rules ────────────────────────────────────────────────────────────────
def _band_above(ink: np.ndarray, y: int) -> tuple[int, int] | None:
    """Zero-ink band directly above row y: returns (start, end) inclusive, or None."""
    end = y - 1
    while end >= 0 and ink[end] > 0:      # we may start inside the line's own top edge
        end -= 1
    start = end
    while start > 0 and ink[start - 1] == 0:
        start -= 1
    return (start, end) if end >= 0 and end >= start else None


def foodmaxx_trim(gray: np.ndarray, ink: np.ndarray, lines) -> tuple[int | None, str]:
    """FoodMaxx (Donald, confirmed 2026-07-05): discard the survey/coupon footer — cut in the
    whitespace directly above the `****` separator that precedes `We want to hear from you!`
    (i.e. just after the `Trx:… Term:… Store:…` line). Keep the card slip above it."""
    banner = next((l for l in lines if re.search(r"want\s*to\s*hear|hear\s*from\s*you", l.text, re.I)), None)
    if banner is None:
        return None, "FoodMaxx: no 'We want to hear from you' banner found — no trim"
    # the line directly above the banner should be the asterisk separator
    above = [l for l in lines if l.bottom <= banner.top + 2]
    sep = above[-1] if above else None
    anchor = banner.top
    if sep is not None and banner.top - sep.bottom < 80 and not re.search(r"Trx|Term|Store|\d{2}:\d{2}", sep.text):
        anchor = sep.top
    band = _band_above(ink, anchor)
    if band is None:
        return None, "FoodMaxx: no whitespace above the survey banner — no trim"
    a, b = band
    row = (a + b) // 2
    # sanity: never trim above the totals
    tot = [l for l in lines if re.search(r"^\W{0,3}TOTAL\b|TENDER", l.text, re.I)]
    if tot and row <= max(l.bottom for l in tot):
        return None, "FoodMaxx: survey banner above the totals?! — no trim"
    return row, f"FoodMaxx footer trimmed at row {row} (blank band {a}-{b}, above '{banner.text[:30]}')"


VENDORS: list[Vendor] = [
    Vendor("FoodMaxx", [r"food\s*ma[x>]{1,3}"], foodmaxx_trim),
    Vendor("Costco", [r"costco", r"wholesale.{0,6}costco"]),
    Vendor("Walmart", [r"wal\W?mart", r"walmart"]),
    Vendor("Target", [r"\btarget\b"]),
    Vendor("Safeway", [r"safeway"]),
    Vendor("Raleys", [r"raley"]),
    Vendor("WinCo", [r"winco"]),
    Vendor("SaveMart", [r"savemart"]),
    Vendor("GroceryOutlet", [r"groceryoutlet"]),
    Vendor("TraderJoes", [r"traderjoe"]),
    Vendor("HomeDepot", [r"homedepot"]),
    Vendor("Lowes", [r"lowe'?s(home|store|\d|$)", r"lowes"]),
    Vendor("TractorSupply", [r"tractorsupply"]),
    Vendor("CVS", [r"\bcvs", r"cvspharmacy"]),
    Vendor("Walgreens", [r"walgreens"]),
    Vendor("Starbucks", [r"starbucks"]),
    Vendor("Chevron", [r"chevron"]),
    Vendor("Shell", [r"\bshell\b"]),
    Vendor("Arco", [r"\barco\b", r"ampm"]),
    Vendor("SmartFinal", [r"smart&final", r"smartandfinal", r"smartfinal"]),
    Vendor("SportsmansWarehouse", [r"sportsmanswarehouse"]),
    Vendor("HarborFreight", [r"harborfreight"]),
    Vendor("Staples", [r"staples"]),
    Vendor("OfficeDepot", [r"officedepot"]),
    Vendor("BestBuy", [r"bestbuy"]),
    Vendor("Kohls", [r"kohl'?s"]),
    Vendor("RossDressForLess", [r"rossdress"]),
    Vendor("DollarTree", [r"dollartree"]),
    Vendor("SamsClub", [r"sam'?sclub"]),
]


def by_name(name: str | None) -> Vendor | None:
    if not name:
        return None
    n = _norm(name)
    for v in VENDORS:
        if _norm(v.name) == n or any(re.search(p, n) for p in v.patterns):
            return v
    return None


def detect(line_texts: list[str], header_lines: int = 25) -> Vendor | None:
    """Header first (where the store name is printed), then anywhere on the receipt.
    Patterns are matched against whole lines with spaces removed, so 'Food Maxx' == 'FoodMaxx'."""
    for chunk in (line_texts[:header_lines], line_texts):
        normed = [re.sub(r"\s+", "", t.lower()) for t in chunk]
        best: tuple[int, Vendor] | None = None
        for v in VENDORS:
            hits = sum(1 for t in normed for p in v.patterns if re.search(p, t))
            if hits and (best is None or hits > best[0]):
                best = (hits, v)
        if best:
            return best[1]
    return None


def select_trim(vendor_name: str | None):
    v = by_name(vendor_name)
    return v.trim if v else None
