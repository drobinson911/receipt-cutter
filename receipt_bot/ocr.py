"""Local OCR with tesseract: slice the tall scan into whitespace-bounded strips and OCR
each to line boxes (absolute y), enough to read the store name and date."""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import cut_receipt  # noqa: E402  (find_cut_points / INK_LEVEL — same whitespace logic as the cutter)

STRIP_H = 1300
TESS_TIMEOUT = 120


@dataclass
class Line:
    text: str
    top: int
    bottom: int
    left: int
    right: int
    conf: float
    words: list = field(default_factory=list)  # (text, left, top, width, height, conf)


def ink_profile(gray: np.ndarray) -> np.ndarray:
    return (gray < cut_receipt.INK_LEVEL).sum(axis=1)


def strip_bounds(gray: np.ndarray, target: int = STRIP_H) -> list[int]:
    """Strip boundaries on text-free rows (same algorithm as the PDF cutter)."""
    h = gray.shape[0]
    rb = gray.mean(axis=1)
    return cut_receipt.find_cut_points(rb, h, target, 200, cut_receipt.BRIGHTNESS_THRESHOLD, ink_profile(gray))


def tesseract(img: Image.Image, psm: int = 4, config: list[str] | None = None, tsv: bool = False) -> str:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img.save(f.name)
        path = f.name
    try:
        cmd = ["tesseract", path, "-", "--psm", str(psm)] + (config or []) + (["tsv"] if tsv else [])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TESS_TIMEOUT)
        return r.stdout
    finally:
        os.unlink(path)


def _lines_from_tsv(tsv: str, y0: int) -> list[Line]:
    groups: dict[tuple, list] = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        try:
            if row["level"] != "5" or not row["text"].strip():
                continue
            key = (row["block_num"], row["par_num"], row["line_num"])
            groups.setdefault(key, []).append((row["text"], int(row["left"]), int(row["top"]) + y0,
                                               int(row["width"]), int(row["height"]), float(row["conf"])))
        except (KeyError, ValueError, TypeError):
            continue
    out = []
    for words in groups.values():
        words.sort(key=lambda w: w[1])
        out.append(Line(" ".join(w[0] for w in words), min(w[2] for w in words), max(w[2] + w[4] for w in words),
                        min(w[1] for w in words), max(w[1] + w[3] for w in words),
                        float(np.mean([w[5] for w in words])), words))
    return out


def ocr_lines(img: Image.Image) -> tuple[list[Line], list[tuple[int, int]]]:
    """OCR the whole receipt strip by strip. Returns lines (absolute y) and strip spans."""
    gray = np.asarray(img.convert("L"))
    bounds = strip_bounds(gray)
    spans = list(zip(bounds[:-1], bounds[1:]))
    lines: list[Line] = []
    for a, b in spans:
        strip = img.crop((0, a, img.width, b))
        lines += _lines_from_tsv(tesseract(strip, psm=4, tsv=True), a)
    lines.sort(key=lambda l: (l.top, l.left))
    return lines, spans
