# Improved Stitching — Design Spec

**Date:** 2026-03-25
**Status:** Draft
**Depends on:** Receipt Capture Improvements, Visual Camera UX
**Fallback if insufficient:** OpenCV.js (WASM) with ORB/SIFT feature matching and homography

## Problem

The current stitching algorithm (1D brightness-row correlation) fails in real-world use because:
1. Users hold the phone at different distances between shots — images have different scales
2. Users shift horizontally between shots — no horizontal alignment handling
3. Brightness-only matching is fragile and low-confidence with noisy photos

The stitching needs to handle ±30% scale difference and slight horizontal shift, producing seamless results comparable to the Tailor app for reasonable use (roughly same distance, roughly straight-on).

## Solution Overview

Two modes: **Smart Stitch** (2D block matching with scale normalization) and **Stack Only** (simple vertical concatenation). Smart Stitch is default; Stack Only is a user-selectable fallback. Smart Stitch automatically falls back to Stack for individual pairs where matching confidence is too low.

## 1. Scale Normalization

Before any matching or stacking, normalize all photos to a consistent receipt width.

- Each photo has been auto-cropped — `croppedCanvas.width` is the detected receipt width in pixels
- **Target width**: The median width across all photos (reduces outlier influence from partial crops)
- For each photo: `scaleFactor = targetWidth / croppedCanvas.width`. Create a new canvas at scaled dimensions, draw the photo scaled, recompute brightness
- This ensures receipt text is the same pixel size across all photos regardless of camera distance

Scale normalization applies to both Smart Stitch and Stack Only modes.

## 2. Smart Stitch — 2D Block Matching

Replace the 1D brightness correlation with 2D template matching:

### Algorithm

1. **Extract template**: Horizontal band (~60px tall, full receipt width) from the bottom ~15% of photo A
2. **Search region**: Top ~40% of photo B
3. **Coarse search**: Downsample template and search region by 2x. Slide template across search region in X and Y. Compute NCC (normalized cross-correlation) at each position. NCC naturally handles brightness differences between shots. Find the top-5 candidate positions.
4. **Fine search**: Around each coarse candidate, search at full resolution in a ±4px window. Pick the (x, y) with the highest NCC.
5. **Confidence check**: Peak NCC must be > 0.6 for a valid match. Below this, fall back to stack mode for this pair.
6. **Output**: `{ offsetX, offsetY, confidence }` — the pixel offset to align photo B relative to photo A, plus match confidence.

### Compositing

1. Align photo B at the found (offsetX, offsetY) relative to photo A
2. The composite width = the overlapping horizontal extent of both photos (crop any overhang so the output is a clean rectangle)
3. Cross-fade the overlap region: for each row in the overlap, linearly blend photo A (decreasing alpha) and photo B (increasing alpha)
4. Draw non-overlapping portions at full opacity

### Performance

- On an ~800px-wide normalized image, 60px template, 40% search region (~320px tall):
  - Coarse pass (400x160): ~64,000 positions × 30×400 pixels each = manageable
  - Fine pass: 5 candidates × ~64 positions × 60×800 pixels each = fast
- Target: <2 seconds per pair on a modern phone

## 3. Stack Only Mode

Available as user choice and as automatic fallback:

- **Process**: Auto-crop, scale-normalize, concatenate vertically
- **Separator**: 2px light gray (#e2e8f0) line between segments
- **No overlap detection**: Photos are placed end-to-end
- **Mixed mode**: If 3 photos and only the 2nd-3rd pair fails matching, stitch 1+2 seamlessly and stack 3 below with separator and warning

## 4. UI Changes

### Session Section

Add a stitch mode toggle:
- **Smart Stitch** (default) — full 2D matching with scale normalization
- **Stack Only** — simple normalized stacking

Small segmented control or toggle placed above the "Done" button.

### Stitch Warnings

More descriptive per-pair feedback:
- "Photos 2 and 3 were stitched with 87% confidence"
- "Photos 3 and 4 could not be matched — stacked instead"
- "Photos scaled to match (photo 2 was 1.3x closer than photo 1)"

## 5. Code Changes

### Replace

- `findStitchOffset()` → `findStitchOffset2D()` in `js/image-processing.js`
  - New signature: `findStitchOffset2D(canvasA, canvasB)` — works on canvas directly (needs pixel access for 2D correlation), not brightness arrays
  - Returns `{ offsetX, offsetY, confidence }` or `null`
- `stitchImages()` → rewritten in `js/image-processing.js`
  - Accepts `{ canvas, brightness }[]` plus `mode: 'smart' | 'stack'`
  - Returns `{ canvas, warnings, pairResults }` where `pairResults` has per-pair match details

### Add

- `normalizeScales(images)` in `js/image-processing.js` — takes array of `{ canvas, brightness }`, returns same structure with all canvases scaled to median width
- `stackImages(canvases)` in `js/image-processing.js` — simple vertical concatenation with separator lines

### Modify

- `js/capture-session.js` — add `stitchMode` property (`'smart'` | `'stack'`), passed through to stitch call
- `index.html` — add stitch mode toggle UI, update warning display, pass mode to stitch

### No changes

- `autoCrop`, `getRowBrightness`, `findCutPoints`, `calcColumnsPerPage` — untouched
- `camera-viewfinder.js` — untouched
- `pdf-generator.js` — untouched (receives the final composite canvas same as before)

## 6. Tests

Replace `tests/stitch.test.mjs` with new test file covering:

- **Scale normalization**: Input canvases of different widths → output all same width with proportional heights
- **2D matching — exact overlap**: Two images with known overlap at (0, 200) → finds correct offset
- **2D matching — horizontal shift**: Overlap at (15, 200) → finds both X and Y offset
- **2D matching — no match**: Completely different images → returns null, triggers stack fallback
- **2D matching — noisy overlap**: Overlap with slight brightness variation → still finds match
- **Stack mode**: Images stacked vertically, output height = sum of heights, correct separator placement

Note: 2D matching tests need synthetic canvas images. Use Node canvas-like data structures (ImageData with RGBA arrays) for the pure-math NCC computation, and mock canvas for compositing tests.

## 7. Out of Scope

- Rotation handling (user must hold phone roughly upright)
- Perspective/keystone correction
- OpenCV.js integration (held as fallback for future iteration)
- Automatic photo ordering (user orders via drag-reorder in session)
