#!/usr/bin/env python3
"""Headless port of receipt-cutter's generatePdf (js/pdf-generator.js + image-processing.js).
Cuts a tall receipt scan into 2-column US-Letter pages at 300 DPI, 1:1 (never shrunk),
slicing only at whitespace rows so text lines are never bisected."""
import sys, math
from PIL import Image
import numpy as np

Image.init()  # register all codecs (PDF save needs the JPEG encoder even when input is PNG)

# ── Constants (identical to js/image-processing.js) ──
DPI = 300
PAGE_W = 2550          # 8.5in * 300
PAGE_H = 3300          # 11in * 300
MARGIN = 105           # 0.35in
GAP = 45               # 0.15in
USABLE_H = PAGE_H - 2 * MARGIN          # 3090
SEARCH_RANGE = 225     # 0.75in
BRIGHTNESS_THRESHOLD = 240
INK_LEVEL = 140        # a pixel this dark is ink
INK_TOLERANCE = 0      # ink pixels allowed on a cut row

def find_cut_points(rb, imgH, target, search, thr, ink=None):
    """Cut points that never bisect a text line.

    The app's original test — mean row brightness > 240 — passes on rows that still
    contain a short, indented line (e.g. FoodMaxx's "6 @ 1/ .98"): the few dark pixels
    barely move a 930px-wide row's average. So when an ink profile is supplied we cut
    only on rows that contain NO ink, choosing the midpoint of the text-free band
    nearest the ideal; the brightness test remains the fallback."""
    cuts = [0]; pos = 0
    while pos + target < imgH:
        ideal = pos + target
        s = max(0, ideal - search); e = min(imgH, ideal + search)
        best = None
        if ink is not None:
            bands = []; run_start = None
            for y in range(s, e):
                if ink[y] <= INK_TOLERANCE:
                    if run_start is None: run_start = y
                elif run_start is not None:
                    bands.append((run_start, y - 1)); run_start = None
            if run_start is not None: bands.append((run_start, e - 1))
            if bands:
                a, b = min(bands, key=lambda t: abs((t[0] + t[1]) // 2 - ideal))
                best = (a + b) // 2
        if best is None:
            for y in range(s, e):
                if rb[y] > thr:
                    if best is None or abs(y - ideal) < abs(best - ideal):
                        best = y
        if best is not None and best > pos:
            cuts.append(best); pos = best
        else:
            cuts.append(ideal); pos = ideal
    cuts.append(imgH)
    return cuts

def cols_per_page(sw, pw, m, g):
    cols = 1
    while 2 * m + (cols + 1) * sw + cols * g <= pw:
        cols += 1
    return cols

def main(src, out):
    img = Image.open(src).convert('RGB')
    W, H = img.size
    arr = np.asarray(img).astype(np.float32)
    row_bright = arr.mean(axis=(1, 2))            # per-row mean of (R+G+B)/3
    row_ink = (np.asarray(img.convert('L')) < INK_LEVEL).sum(axis=1)   # ink pixels per row

    cuts = find_cut_points(row_bright, H, USABLE_H, SEARCH_RANGE, BRIGHTNESS_THRESHOLD, row_ink)
    num_strips = len(cuts) - 1
    cols = cols_per_page(W, PAGE_W, MARGIN, GAP)
    num_pages = math.ceil(num_strips / cols)

    # Report cut geometry so we can verify no strip exceeds usable height
    heights = [cuts[i+1]-cuts[i] for i in range(num_strips)]
    print(f"img {W}x{H}  strips={num_strips}  cols/page={cols}  pages={num_pages}")
    print(f"strip heights: {heights}  (USABLE_H={USABLE_H})")
    print(f"cut points: {cuts}")
    ink_on_cuts = [(c, int(row_ink[c])) for c in cuts[1:-1]]
    print(f"ink pixels on each interior cut row (must be 0): {ink_on_cuts}")

    pages = []
    for p in range(num_pages):
        page = Image.new('RGB', (PAGE_W, PAGE_H), 'white')
        start = p * cols; end = min(start + cols, num_strips)
        n = end - start
        total_w = n * W + (n - 1) * GAP
        x_start = round((PAGE_W - total_w) / 2)
        for c in range(n):
            s = start + c
            strip = img.crop((0, cuts[s], W, cuts[s+1]))
            page.paste(strip, (x_start + c * (W + GAP), MARGIN))
        pages.append(page)

    pages[0].save(out, save_all=True, append_images=pages[1:], resolution=float(DPI))
    print(f"wrote {out}  ({num_pages} pages)")

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
