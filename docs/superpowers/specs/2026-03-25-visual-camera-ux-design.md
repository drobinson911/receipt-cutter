# Visual Camera UX — Design Spec

**Date:** 2026-03-25
**Status:** Draft
**Depends on:** Receipt Capture Improvements (2026-03-25)

## Problem

Users have no visual feedback during photo capture:
1. No indication of where the receipt edges are being detected
2. No guidance for overlapping consecutive photos of long receipts

## Solution Overview

Replace `<input type="file" capture>` with a custom `getUserMedia` camera viewfinder featuring real-time crop boundary detection and a ghost overlay for overlap alignment.

## 1. Custom Camera Viewfinder

Replace the native camera handoff with a full-screen custom camera view.

- **Stream**: `getUserMedia({ video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } } })`
- **Layout**: Full-viewport `<video>` element with a `<canvas>` overlay of identical size, positioned absolutely on top
- **Controls bar** at bottom of viewfinder:
  - **Flash/torch toggle** (left) — uses `track.applyConstraints({ advanced: [{ torch: true }] })`, hidden if unsupported
  - **Capture button** (center) — large circular button
  - **Ghost toggle** (right, eye icon) — show/hide the overlap ghost overlay. Defaults to visible. Only shown when a previous photo exists.
  - **Close/cancel** (top-left or top-right) — stops the stream, returns to capture session
- **Frame capture**: On capture tap, draw current video frame to a hidden full-resolution canvas, convert to blob, feed into `session.addPhoto()`. Brief flash animation, then back to viewfinder for next photo.
- **Exit**: "Done" button to return to session screen and see all captured photos
- **Fallback**: The `<input type="file">` upload path remains for desktop and uploading existing photos

## 2. Real-Time Crop Boundary Overlay

Green rectangle on the viewfinder showing detected receipt edges.

- **Processing loop**: `requestAnimationFrame`, throttled to ~15fps (~66ms interval)
- **Per frame**:
  - Draw video frame to a tiny analysis canvas (~200px wide, proportional height)
  - Run `autoCrop()` on the ImageData
  - Scale the returned `{ x, y, w, h }` back to viewfinder coordinates
  - Draw a green rounded rectangle on the overlay canvas
  - Dim the area outside the rectangle with semi-transparent fill
- **Smoothing**: Lerp between previous and current rectangle at ~30% per frame to prevent jitter
- **No receipt detected**: If `autoCrop` returns the full frame (fallback), hide the rectangle entirely — do not draw a misleading border around the whole viewfinder
- **Performance**: 200px downsample keeps `autoCrop` well under 50ms. If device is slow, drop to 10fps.

## 3. Ghost Overlap Guide

Semi-transparent overlay of the previous photo's bottom edge to guide alignment.

- **When visible**: Only when `session.photos.length >= 1` and the viewfinder is open
- **Content**: Bottom ~20% of the previous photo's cropped canvas
- **Position**: Top of the viewfinder (user continues downward on receipt)
- **Styling**: ~30% opacity, subtle horizontal dashed line at the bottom edge of the ghost marking "align here"
- **Sizing**: Scaled to match viewfinder width, height scales proportionally
- **Toggle**: Eye icon button in controls bar to show/hide. Defaults to visible.
- **Updates**: Ghost refreshes each time a new photo is captured, always showing the most recent photo's bottom edge
- **First photo**: No ghost shown (no previous photo exists)

## 4. File Structure Changes

```
js/
  camera-viewfinder.js   (new — getUserMedia, overlay rendering, capture, controls)
  capture-session.js     (minor modification — accept blob/canvas in addition to File)
  image-processing.js    (no changes — autoCrop already works on ImageData)
index.html               (add viewfinder HTML section, CSS for camera UI, wire up camera-viewfinder.js)
```

### camera-viewfinder.js responsibilities:
- Open/close camera stream
- Render video to screen
- Run crop detection loop (calls autoCrop from image-processing.js)
- Draw crop boundary overlay
- Draw ghost overlay
- Handle capture (frame grab → addPhoto)
- Flash toggle
- Ghost toggle

## 5. Integration with Existing Flow

- "Take Photo" button in upload card and "Add Photo" in session now open the custom viewfinder instead of triggering `<input capture>`
- "Upload File" button still uses `<input type="file">` (unchanged)
- After capture, photo goes through same `session.addPhoto()` pipeline (auto-crop, brightness analysis)
- The viewfinder's real-time crop detection is purely visual — the actual crop for the PDF pipeline still happens in `addPhoto()` at full resolution

## 6. Browser Compatibility

- `getUserMedia` with `facingMode: 'environment'`: Chrome Android, Safari iOS 11+, Firefox Android
- Torch/flash: Chrome Android only (best-effort, hidden if unsupported)
- Fallback: If `getUserMedia` is denied or unavailable, fall back to the existing `<input type="file" capture>` behavior with a message explaining why the custom camera isn't available

## 7. Out of Scope

- Pinch-to-zoom (can be added later)
- Video recording
- Multiple camera switching (front/back)
- Exposure/white balance controls
