# Receipt Capture Improvements — Design Spec

**Date:** 2026-03-25
**Status:** Draft
**Approach:** Multi-photo stitching with auto-crop (Approach A)
**Fallback:** OpenCV.js (Approach B) if brightness-correlation stitching proves insufficient

## Problem

1. Photos include background clutter (table, counter) — need auto-crop to receipt edges
2. Long receipts (Costco-style) lose resolution when captured in a single far-away shot
3. App should work well on both phone and desktop, with phone as the primary use case

## Solution Overview

Add a multi-photo capture session with per-photo auto-crop and vertical stitching. The stitched composite feeds into the existing cut-to-PDF pipeline unchanged. Make the app installable as a PWA.

## 1. Auto-Crop (Edge Detection)

When a photo is captured or uploaded:

1. Draw to an offscreen canvas, downsampled to ~800px wide for analysis speed
2. Convert to grayscale, apply brightness threshold (>200 = receipt paper, below = background)
3. Scan inward from each edge (top, bottom, left, right) to find the first rows/columns crossing the threshold — produces a bounding rectangle
4. Add ~10px margin, crop the original full-resolution image to that rectangle
5. Show cropped preview with "use original" fallback if auto-crop is wrong

No external libraries — canvas pixel math, extending the existing `getRowBrightness()` pattern.

## 2. Multi-Photo Stitching

For long receipts captured across multiple photos:

1. **Overlap requirement:** ~20% vertical overlap between consecutive shots. App shows a tip on first use.
2. **Overlap detection:** Compare bottom portion of photo N with top portion of photo N+1 using row-brightness signatures. Slide a correlation window to find the vertical offset with highest similarity.
3. **Correlation scoring:** If the best match score is below a confidence threshold, warn the user and suggest retaking that segment.
4. **Composite assembly:** Draw photos onto one tall canvas at their resolved offsets. Blend overlap regions with linear fade to hide seams.
5. **Output:** The tall composite image feeds directly into the existing `findCutPoints()` and PDF generation pipeline — no downstream changes needed.

### Stitching Algorithm Detail

- Extract brightness signatures (one value per row) for the overlap candidate regions
- Compute normalized cross-correlation at each possible vertical offset
- Peak correlation above threshold (e.g., 0.7) = valid match
- Below threshold = warn user, allow retake or manual accept

## 3. UX Flow

### Capture Session

The camera button now starts a capture session instead of a single-shot capture:

1. **Session screen** shows:
   - Vertical strip of thumbnails (ordered top-to-bottom, matching receipt order)
   - "Take Photo" button (camera capture)
   - "Upload Photo" button (file picker, for desktop or pre-taken images)
   - **Back/Cancel** button on each thumbnail to discard and retake
   - **Reorder** via drag to rearrange misordered photos
   - Each photo is auto-cropped immediately with preview shown

2. **"Done / Stitch"** button:
   - Single photo: auto-crop only, straight to existing flow
   - Multiple photos: runs stitching pipeline, shows scrollable preview of composite

3. **Post-stitch review:**
   - If stitching looks wrong, user can go back, remove/retake problem photos, re-stitch
   - "Convert to PDF" proceeds with the composite through the existing pipeline

### Desktop Support

- Drag-and-drop multiple files into the session, ordered by drop sequence
- File picker supports multiple selection

### Error Recovery

- Back/Cancel button to discard any individual photo
- "Use original" fallback if auto-crop is wrong on a particular photo
- Stitch warning if overlap detection confidence is low
- Full session cancel to start over

## 4. PWA (Installable Web App)

### manifest.json

- `name`: "Receipt Cutter"
- `short_name`: "Receipt Cutter"
- `start_url`: "/"
- `display`: "standalone"
- `background_color` and `theme_color`: match current app styling
- `icons`: app icons at 192x192 and 512x512

### Service Worker

- Cache-first strategy for app shell (index.html, manifest, icons)
- The app is already self-contained (single HTML file + CDN jsPDF), so offline support is straightforward
- Cache jsPDF CDN resource for offline use
- Register service worker from index.html

### Install Prompt

- No custom install banner — rely on browser's native install prompt
- Add `<meta name="theme-color">` and `<link rel="manifest">` to index.html

## 5. File Structure Changes

Current: single `index.html` + `tests/`

After:
```
receipt-cutter/
  index.html          (updated with new capture session UI, stitching logic, SW registration)
  manifest.json       (new — PWA manifest)
  sw.js               (new — service worker)
  icons/
    icon-192.png      (new — app icon)
    icon-512.png      (new — app icon)
  tests/
    receipt-cutter.test.mjs  (updated with new test cases)
  docs/
    superpowers/specs/...
```

## 6. Testing

- **Auto-crop:** Unit tests with synthetic images (bright rectangle on dark background) verifying correct bounding box detection
- **Stitching:** Unit tests with overlapping brightness signatures verifying correct offset detection and correlation scoring
- **Edge cases:** Single photo (no stitch needed), no valid overlap found (warning triggered), photos with minimal overlap, very long receipts (5+ segments)
- **PWA:** Manual verification of install prompt and offline functionality

## 7. Out of Scope

- OCR / text extraction from receipts
- Cloud storage or sync
- Automatic receipt categorization
- OpenCV.js integration (held as fallback only — not implemented unless Approach A proves insufficient)
