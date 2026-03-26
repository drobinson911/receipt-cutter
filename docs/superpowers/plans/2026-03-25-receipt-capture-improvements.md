# Receipt Capture Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-photo capture with auto-crop, stitching, and PWA support to the receipt-cutter app.

**Architecture:** Extract JS logic from index.html into separate modules. Add auto-crop (edge detection via brightness scanning), multi-photo stitching (brightness-signature correlation), a capture session UI, and PWA files (manifest.json + service worker). The existing PDF pipeline remains unchanged — it receives the final composite image.

**Tech Stack:** Vanilla JS (ES modules for testable code), Canvas API, jsPDF (CDN), Service Worker API, Web App Manifest.

---

## File Structure

After implementation:

```
receipt-cutter/
  index.html              (rewritten — capture session UI, imports modules via <script>)
  manifest.json           (new — PWA manifest)
  sw.js                   (new — service worker, cache-first for app shell + jsPDF CDN)
  icons/
    icon-192.png          (new — app icon)
    icon-512.png          (new — app icon)
  js/
    image-processing.js   (new — getRowBrightness, findCutPoints, calcColumnsPerPage, autoCrop, findStitchOffset, stitchImages)
    pdf-generator.js      (new — processReceipt pipeline, extracted from index.html)
    capture-session.js    (new — capture session state management and UI logic)
  tests/
    image-processing.test.mjs  (rename + expand from receipt-cutter.test.mjs)
    stitch.test.mjs       (new — stitching algorithm tests)
    autocrop.test.mjs     (new — auto-crop algorithm tests)
  docs/
    superpowers/...
```

**Key decomposition decisions:**
- `image-processing.js` holds all pure pixel-math functions (testable without DOM)
- `pdf-generator.js` holds the PDF pipeline (depends on jsPDF + canvas)
- `capture-session.js` holds session state + UI wiring (depends on DOM)
- Tests import from `image-processing.js` directly — no more inline function copies

---

### Task 1: Extract JS into Modules

Move existing functions out of index.html into importable JS files so new code can share them and tests can import directly.

**Files:**
- Create: `js/image-processing.js`
- Create: `js/pdf-generator.js`
- Modify: `index.html` (remove inline JS, add script imports)
- Modify: `tests/receipt-cutter.test.mjs` (import from js/ instead of inline copies)

- [ ] **Step 1: Create `js/image-processing.js` with existing pure functions**

```js
// js/image-processing.js

export const DPI = 300;
export const PAGE_W_IN = 8.5;
export const PAGE_H_IN = 11.0;
export const MARGIN_IN = 0.35;
export const GAP_IN = 0.15;
export const SEARCH_RANGE_IN = 0.75;
export const BRIGHTNESS_THRESHOLD = 240;

export const PAGE_W = Math.round(PAGE_W_IN * DPI);
export const PAGE_H = Math.round(PAGE_H_IN * DPI);
export const MARGIN = Math.round(MARGIN_IN * DPI);
export const GAP = Math.round(GAP_IN * DPI);
export const USABLE_H = PAGE_H - 2 * MARGIN;
export const SEARCH_RANGE = Math.round(SEARCH_RANGE_IN * DPI);

/**
 * Returns a Float32Array of average brightness per row.
 */
export function getRowBrightness(canvas) {
  const ctx = canvas.getContext('2d');
  const { width, height } = canvas;
  const imageData = ctx.getImageData(0, 0, width, height);
  const data = imageData.data;
  const rowBrightness = new Float32Array(height);

  for (let y = 0; y < height; y++) {
    let sum = 0;
    const rowStart = y * width * 4;
    for (let x = 0; x < width; x++) {
      const i = rowStart + x * 4;
      sum += (data[i] + data[i + 1] + data[i + 2]) / 3;
    }
    rowBrightness[y] = sum / width;
  }
  return rowBrightness;
}

/**
 * Finds cut points between text lines.
 */
export function findCutPoints(rowBrightness, imgHeight, targetHeight, searchRange, brightnessThreshold) {
  const cuts = [0];
  let pos = 0;

  while (pos + targetHeight < imgHeight) {
    const idealCut = pos + targetHeight;
    const searchStart = Math.max(0, idealCut - searchRange);
    const searchEnd = Math.min(imgHeight, idealCut + searchRange);

    let bestCut = null;
    for (let y = searchStart; y < searchEnd; y++) {
      if (rowBrightness[y] > brightnessThreshold) {
        if (bestCut === null || Math.abs(y - idealCut) < Math.abs(bestCut - idealCut)) {
          bestCut = y;
        }
      }
    }

    if (bestCut !== null) {
      cuts.push(bestCut);
      pos = bestCut;
    } else {
      cuts.push(idealCut);
      pos = idealCut;
    }
  }

  cuts.push(imgHeight);
  return cuts;
}

/**
 * Calculates how many strip columns fit side-by-side on one page.
 */
export function calcColumnsPerPage(stripWidth, pageWidth, margin, gap) {
  let cols = 1;
  while (2 * margin + (cols + 1) * stripWidth + cols * gap <= pageWidth) {
    cols++;
  }
  return cols;
}
```

- [ ] **Step 2: Create `js/pdf-generator.js` with the PDF pipeline**

```js
// js/pdf-generator.js

import {
  getRowBrightness, findCutPoints, calcColumnsPerPage,
  PAGE_W, PAGE_H, MARGIN, GAP, USABLE_H, SEARCH_RANGE, BRIGHTNESS_THRESHOLD
} from './image-processing.js';

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Generates a PDF from a receipt image (HTMLImageElement).
 * onProgress(text, percent) is called for UI updates.
 * Returns a blob URL for the generated PDF.
 */
export async function generatePdf(image, onProgress) {
  onProgress('Loading image…', 5);
  await sleep(50);

  const canvas = document.createElement('canvas');
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(image, 0, 0);

  onProgress('Analysing brightness…', 15);
  await sleep(50);

  const rowBrightness = getRowBrightness(canvas);

  onProgress('Finding cut points…', 30);
  await sleep(50);

  const imgW = canvas.width;
  const imgH = canvas.height;
  const cutPoints = findCutPoints(rowBrightness, imgH, USABLE_H, SEARCH_RANGE, BRIGHTNESS_THRESHOLD);
  const numStrips = cutPoints.length - 1;

  const colsPerPage = calcColumnsPerPage(imgW, PAGE_W, MARGIN, GAP);

  onProgress('Creating PDF…', 45);
  await sleep(50);

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({
    unit: 'px',
    format: [PAGE_W, PAGE_H],
    hotfixes: ['px_scaling'],
  });

  const numPages = Math.ceil(numStrips / colsPerPage);

  for (let p = 0; p < numPages; p++) {
    if (p > 0) doc.addPage([PAGE_W, PAGE_H]);

    const pageStrips = [];
    const stripStart = p * colsPerPage;
    const stripEnd = Math.min(stripStart + colsPerPage, numStrips);

    for (let s = stripStart; s < stripEnd; s++) {
      const top = cutPoints[s];
      const bottom = cutPoints[s + 1];
      const sh = bottom - top;

      const stripCanvas = document.createElement('canvas');
      stripCanvas.width = imgW;
      stripCanvas.height = sh;
      const sCtx = stripCanvas.getContext('2d');
      sCtx.drawImage(canvas, 0, top, imgW, sh, 0, 0, imgW, sh);
      pageStrips.push(stripCanvas);
    }

    const numCols = pageStrips.length;
    const totalColsW = numCols * imgW + (numCols - 1) * GAP;
    const xStart = Math.round((PAGE_W - totalColsW) / 2);

    for (let c = 0; c < numCols; c++) {
      const x = xStart + c * (imgW + GAP);
      const y = MARGIN;
      const stripCanvas = pageStrips[c];
      const imgData = stripCanvas.toDataURL('image/jpeg', 0.92);
      doc.addImage(imgData, 'JPEG', x, y, imgW, stripCanvas.height);
      stripCanvas.width = 0;
      stripCanvas.height = 0;
    }

    const pct = 45 + Math.round(((p + 1) / numPages) * 50);
    onProgress(`Rendering page ${p + 1} of ${numPages}…`, pct);
    await sleep(30);
  }

  onProgress('Finalising…', 97);
  await sleep(50);

  const pdfBlob = doc.output('blob');

  return {
    blobUrl: URL.createObjectURL(pdfBlob),
    numPages,
    numStrips,
    colsPerPage,
  };
}
```

- [ ] **Step 3: Update `index.html` to use module imports**

Replace the entire `<script>` block (lines 331-693) with:

```html
  <script type="module">
    import { generatePdf } from './js/pdf-generator.js';

    // ─── State ───────────────────────────────────────────────────────────────
    let loadedImage = null;
    let loadedFileName = '';
    let generatedPdfUrl = null;

    // ─── DOM refs ────────────────────────────────────────────────────────────
    const uploadArea = document.getElementById('upload-area');
    const inputCamera = document.getElementById('input-camera');
    const inputFile = document.getElementById('input-file');
    const btnCamera = document.getElementById('btn-camera');
    const btnFile = document.getElementById('btn-file');
    const previewSection = document.getElementById('preview-section');
    const previewImg = document.getElementById('preview-img');
    const previewFilename = document.getElementById('preview-filename');
    const previewDims = document.getElementById('preview-dims');
    const previewSize = document.getElementById('preview-size');
    const btnConvert = document.getElementById('btn-convert');
    const progressSection = document.getElementById('progress-section');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const resultSection = document.getElementById('result-section');
    const resultInfo = document.getElementById('result-info');
    const btnDownload = document.getElementById('btn-download');
    const btnPrint = document.getElementById('btn-print');
    const resetLink = document.getElementById('reset-link');
    const btnReset = document.getElementById('btn-reset');

    // ─── Upload Handling ─────────────────────────────────────────────────────
    btnCamera.addEventListener('click', () => inputCamera.click());
    btnFile.addEventListener('click', () => inputFile.click());

    inputCamera.addEventListener('change', e => {
      if (e.target.files[0]) handleFile(e.target.files[0]);
    });
    inputFile.addEventListener('change', e => {
      if (e.target.files[0]) handleFile(e.target.files[0]);
    });

    uploadArea.addEventListener('dragover', e => {
      e.preventDefault();
      uploadArea.classList.add('drag-over');
    });
    uploadArea.addEventListener('dragleave', () => {
      uploadArea.classList.remove('drag-over');
    });
    uploadArea.addEventListener('drop', e => {
      e.preventDefault();
      uploadArea.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file && file.type.startsWith('image/')) {
        handleFile(file);
      }
    });

    function handleFile(file) {
      const reader = new FileReader();
      reader.onload = e => {
        const img = new Image();
        img.onload = () => showPreview(img, file);
        img.src = e.target.result;
      };
      reader.readAsDataURL(file);
    }

    function showPreview(img, file) {
      loadedImage = img;
      loadedFileName = file.name.replace(/\.[^.]+$/, '');

      previewImg.src = img.src;
      previewFilename.textContent = file.name;
      previewDims.textContent = `${img.naturalWidth} × ${img.naturalHeight} px`;
      previewSize.textContent = formatBytes(file.size);

      uploadArea.closest('.card').style.display = 'none';
      previewSection.style.display = 'block';
    }

    function formatBytes(bytes) {
      if (bytes < 1024) return bytes + ' B';
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    // ─── PDF Generation ──────────────────────────────────────────────────────
    function updateProgress(text, percent) {
      progressText.textContent = text;
      progressBar.style.width = percent + '%';
    }

    btnConvert.addEventListener('click', async () => {
      btnConvert.disabled = true;
      previewSection.style.display = 'none';
      progressSection.style.display = 'block';

      try {
        const result = await generatePdf(loadedImage, updateProgress);

        if (generatedPdfUrl) URL.revokeObjectURL(generatedPdfUrl);
        generatedPdfUrl = result.blobUrl;

        updateProgress('Done!', 100);
        await new Promise(r => setTimeout(r, 200));

        progressSection.style.display = 'none';
        resultSection.style.display = 'block';
        resetLink.style.display = 'block';

        resultInfo.textContent =
          `${result.numPages} page${result.numPages !== 1 ? 's' : ''} · ` +
          `${result.numStrips} strip${result.numStrips !== 1 ? 's' : ''} · ` +
          `${result.colsPerPage} column${result.colsPerPage !== 1 ? 's' : ''} per page`;
      } catch (err) {
        console.error('processReceipt failed:', err);
        progressSection.style.display = 'none';
        previewSection.style.display = 'block';
        btnConvert.disabled = false;
        alert('An error occurred while processing the receipt. Please try again.');
      }
    });

    // ─── Download & Print ────────────────────────────────────────────────────
    btnDownload.addEventListener('click', () => {
      if (!generatedPdfUrl) return;
      const a = document.createElement('a');
      a.href = generatedPdfUrl;
      a.download = `receipt_${loadedFileName}_letter.pdf`;
      a.click();
    });

    btnPrint.addEventListener('click', () => {
      if (!generatedPdfUrl) return;
      const printWindow = window.open(generatedPdfUrl);
      if (printWindow) {
        printWindow.addEventListener('load', () => printWindow.print());
      }
    });

    // ─── Reset ───────────────────────────────────────────────────────────────
    btnReset.addEventListener('click', (e) => {
      e.preventDefault();
      loadedImage = null;
      loadedFileName = '';
      if (generatedPdfUrl) {
        URL.revokeObjectURL(generatedPdfUrl);
        generatedPdfUrl = null;
      }
      inputCamera.value = '';
      inputFile.value = '';
      previewImg.src = '';
      previewFilename.textContent = '';
      previewDims.textContent = '';
      previewSize.textContent = '';
      progressBar.style.width = '0%';
      progressText.textContent = 'Starting…';
      btnConvert.disabled = false;
      resultInfo.textContent = '';

      uploadArea.closest('.card').style.display = 'block';
      previewSection.style.display = 'none';
      progressSection.style.display = 'none';
      resultSection.style.display = 'none';
      resetLink.style.display = 'none';
    });
  </script>
```

- [ ] **Step 4: Update tests to import from `js/image-processing.js`**

Replace the inline function copies and import line in `tests/receipt-cutter.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findCutPoints, calcColumnsPerPage } from '../js/image-processing.js';

// Remove the inline copies of findCutPoints and calcColumnsPerPage (lines 18-59)
// Keep everything from line 61 onward (helpers and tests) unchanged.
```

- [ ] **Step 5: Run tests to verify extraction didn't break anything**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/receipt-cutter.test.mjs`
Expected: All 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add js/image-processing.js js/pdf-generator.js index.html tests/receipt-cutter.test.mjs
git commit -m "refactor: extract JS into modules for testability"
```

---

### Task 2: Auto-Crop Algorithm

Implement brightness-based edge detection to crop photos to receipt boundaries.

**Files:**
- Modify: `js/image-processing.js` (add `autoCrop`)
- Create: `tests/autocrop.test.mjs`

- [ ] **Step 1: Write failing tests for `autoCrop`**

Create `tests/autocrop.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { autoCrop } from '../js/image-processing.js';

/**
 * Build a flat RGBA Uint8ClampedArray simulating an image.
 * bg = background brightness, fg = receipt brightness.
 * Receipt occupies the rectangle (rx, ry, rw, rh) within (width x height).
 */
function makeImageData(width, height, rx, ry, rw, rh, bg = 40, fg = 250) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const inReceipt = x >= rx && x < rx + rw && y >= ry && y < ry + rh;
      const v = inReceipt ? fg : bg;
      data[i] = v;
      data[i + 1] = v;
      data[i + 2] = v;
      data[i + 3] = 255;
    }
  }
  return { data, width, height };
}

test('autoCrop: detects centered receipt on dark background', () => {
  // 400x600 image with receipt at (50, 80, 300, 440)
  const imageData = makeImageData(400, 600, 50, 80, 300, 440);
  const rect = autoCrop(imageData, 200);

  // Should be close to (50, 80, 300, 440) ± margin
  assert.ok(rect.x <= 50, `x=${rect.x} should be <= 50`);
  assert.ok(rect.y <= 80, `y=${rect.y} should be <= 80`);
  assert.ok(rect.x + rect.w >= 350, `right edge should be >= 350`);
  assert.ok(rect.y + rect.h >= 520, `bottom edge should be >= 520`);
});

test('autoCrop: returns full image when entire image is bright', () => {
  // All-white image — receipt IS the whole image
  const imageData = makeImageData(400, 600, 0, 0, 400, 600, 250, 250);
  const rect = autoCrop(imageData, 200);

  assert.equal(rect.x, 0);
  assert.equal(rect.y, 0);
  assert.equal(rect.w, 400);
  assert.equal(rect.h, 600);
});

test('autoCrop: returns full image when entire image is dark', () => {
  // All-dark image — no receipt detected, return full image as fallback
  const imageData = makeImageData(400, 600, 0, 0, 0, 0, 40, 40);
  const rect = autoCrop(imageData, 200);

  assert.equal(rect.x, 0);
  assert.equal(rect.y, 0);
  assert.equal(rect.w, 400);
  assert.equal(rect.h, 600);
});

test('autoCrop: receipt at edge of image crops correctly', () => {
  // Receipt flush against left and top edges
  const imageData = makeImageData(400, 600, 0, 0, 200, 400);
  const rect = autoCrop(imageData, 200);

  assert.equal(rect.x, 0);
  assert.equal(rect.y, 0);
  assert.ok(rect.w >= 200 && rect.w <= 210, `w=${rect.w}`);
  assert.ok(rect.h >= 400 && rect.h <= 410, `h=${rect.h}`);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/autocrop.test.mjs`
Expected: FAIL — `autoCrop` is not exported from `image-processing.js`

- [ ] **Step 3: Implement `autoCrop` in `js/image-processing.js`**

Add to the end of `js/image-processing.js`:

```js
/**
 * Auto-crop to receipt boundaries using brightness thresholding.
 * Accepts an ImageData-like object { data, width, height } and a brightness threshold.
 * Returns { x, y, w, h } bounding rectangle.
 * Scans inward from each edge to find the first row/column exceeding the threshold.
 * Falls back to full image if no bright region found.
 */
export function autoCrop(imageData, threshold = 200) {
  const { data, width, height } = imageData;
  const MARGIN_PX = 10;

  // Helper: average brightness of a pixel
  function pixelBrightness(x, y) {
    const i = (y * width + x) * 4;
    return (data[i] + data[i + 1] + data[i + 2]) / 3;
  }

  // Helper: fraction of bright pixels in a row
  function rowBrightFraction(y) {
    let count = 0;
    for (let x = 0; x < width; x++) {
      if (pixelBrightness(x, y) > threshold) count++;
    }
    return count / width;
  }

  // Helper: fraction of bright pixels in a column
  function colBrightFraction(x) {
    let count = 0;
    for (let y = 0; y < height; y++) {
      if (pixelBrightness(x, y) > threshold) count++;
    }
    return count / height;
  }

  // A row/column is "receipt" if >= 20% of its pixels are bright
  const RECEIPT_FRAC = 0.20;

  // Scan from top
  let top = 0;
  for (let y = 0; y < height; y++) {
    if (rowBrightFraction(y) >= RECEIPT_FRAC) { top = y; break; }
  }

  // Scan from bottom
  let bottom = height - 1;
  for (let y = height - 1; y >= 0; y--) {
    if (rowBrightFraction(y) >= RECEIPT_FRAC) { bottom = y; break; }
  }

  // Scan from left
  let left = 0;
  for (let x = 0; x < width; x++) {
    if (colBrightFraction(x) >= RECEIPT_FRAC) { left = x; break; }
  }

  // Scan from right
  let right = width - 1;
  for (let x = width - 1; x >= 0; x--) {
    if (colBrightFraction(x) >= RECEIPT_FRAC) { right = x; break; }
  }

  // If no bright region found at all, return full image
  if (top >= bottom || left >= right) {
    return { x: 0, y: 0, w: width, h: height };
  }

  // Add margin, clamp to image bounds
  const x = Math.max(0, left - MARGIN_PX);
  const y = Math.max(0, top - MARGIN_PX);
  const w = Math.min(width, right + MARGIN_PX + 1) - x;
  const h = Math.min(height, bottom + MARGIN_PX + 1) - y;

  return { x, y, w, h };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/autocrop.test.mjs`
Expected: All 4 tests pass.

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/receipt-cutter.test.mjs`
Expected: All 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add js/image-processing.js tests/autocrop.test.mjs
git commit -m "feat: add autoCrop function with brightness-based edge detection"
```

---

### Task 3: Stitching Algorithm

Implement overlap detection and image stitching using brightness-signature correlation.

**Files:**
- Modify: `js/image-processing.js` (add `findStitchOffset`, `stitchImages`)
- Create: `tests/stitch.test.mjs`

- [ ] **Step 1: Write failing tests for `findStitchOffset`**

Create `tests/stitch.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findStitchOffset, stitchImages } from '../js/image-processing.js';

/**
 * Build a row-brightness Float32Array with a distinctive pattern.
 * pattern is repeated to fill the given height.
 */
function makeBrightness(height, pattern) {
  const arr = new Float32Array(height);
  for (let i = 0; i < height; i++) {
    arr[i] = pattern[i % pattern.length];
  }
  return arr;
}

test('findStitchOffset: detects exact overlap with matching patterns', () => {
  // Image A is 1000 rows, image B is 1000 rows.
  // The bottom 200 rows of A match the top 200 rows of B.
  const pattern = [10, 50, 200, 180, 30, 245, 100, 60];
  const aHeight = 1000;
  const bHeight = 1000;
  const overlap = 200;

  const aBrightness = new Float32Array(aHeight);
  const bBrightness = new Float32Array(bHeight);

  // Fill A with one pattern
  for (let i = 0; i < aHeight; i++) aBrightness[i] = (i * 7 + 13) % 256;
  // Copy bottom 200 of A to top 200 of B
  for (let i = 0; i < overlap; i++) bBrightness[i] = aBrightness[aHeight - overlap + i];
  // Fill rest of B with different data
  for (let i = overlap; i < bHeight; i++) bBrightness[i] = (i * 11 + 37) % 256;

  const result = findStitchOffset(aBrightness, bBrightness, 0.1, 0.5);

  assert.ok(result !== null, 'Should find a match');
  assert.equal(result.offset, overlap, `Expected offset ${overlap}, got ${result.offset}`);
  assert.ok(result.confidence > 0.7, `Confidence ${result.confidence} should be > 0.7`);
});

test('findStitchOffset: returns null when images do not overlap', () => {
  // Two completely different brightness patterns
  const aBrightness = new Float32Array(500);
  const bBrightness = new Float32Array(500);
  for (let i = 0; i < 500; i++) {
    aBrightness[i] = 50; // uniform dark
    bBrightness[i] = 200; // uniform bright
  }

  const result = findStitchOffset(aBrightness, bBrightness, 0.1, 0.5);

  // Uniform signals have no distinctive features — should return null or low confidence
  // (uniform correlation is undefined/degenerate, implementation should handle gracefully)
  if (result !== null) {
    assert.ok(result.confidence < 0.7, `Confidence should be low for non-overlapping images`);
  }
});

test('findStitchOffset: finds offset with noisy overlap', () => {
  // Similar to test 1 but with ±5 noise added to the overlap region
  const aHeight = 800;
  const bHeight = 800;
  const overlap = 150;

  const aBrightness = new Float32Array(aHeight);
  const bBrightness = new Float32Array(bHeight);

  for (let i = 0; i < aHeight; i++) aBrightness[i] = (i * 7 + 13) % 256;
  for (let i = 0; i < overlap; i++) {
    const noise = (Math.sin(i * 17) * 5); // deterministic "noise"
    bBrightness[i] = Math.max(0, Math.min(255, aBrightness[aHeight - overlap + i] + noise));
  }
  for (let i = overlap; i < bHeight; i++) bBrightness[i] = (i * 11 + 37) % 256;

  const result = findStitchOffset(aBrightness, bBrightness, 0.1, 0.5);

  assert.ok(result !== null, 'Should find a match despite noise');
  assert.ok(Math.abs(result.offset - overlap) <= 2, `Offset ${result.offset} should be within 2 of ${overlap}`);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/stitch.test.mjs`
Expected: FAIL — `findStitchOffset` is not exported

- [ ] **Step 3: Implement `findStitchOffset` in `js/image-processing.js`**

Add to the end of `js/image-processing.js`:

```js
/**
 * Find the vertical overlap between two images using brightness-signature correlation.
 * aBrightness: Float32Array of row brightness for image A (top image)
 * bBrightness: Float32Array of row brightness for image B (bottom image)
 * minOverlapFrac: minimum overlap as fraction of shorter image height (e.g., 0.1 = 10%)
 * maxOverlapFrac: maximum overlap as fraction of shorter image height (e.g., 0.5 = 50%)
 * Returns { offset, confidence } or null if no good match.
 * offset = number of rows from top of B that overlap with bottom of A.
 */
export function findStitchOffset(aBrightness, bBrightness, minOverlapFrac = 0.1, maxOverlapFrac = 0.5) {
  const aLen = aBrightness.length;
  const bLen = bBrightness.length;
  const shorter = Math.min(aLen, bLen);
  const minOverlap = Math.max(20, Math.floor(shorter * minOverlapFrac));
  const maxOverlap = Math.floor(shorter * maxOverlapFrac);

  let bestOffset = 0;
  let bestScore = -Infinity;

  for (let overlap = minOverlap; overlap <= maxOverlap; overlap++) {
    // Compare bottom `overlap` rows of A with top `overlap` rows of B
    const aStart = aLen - overlap;

    // Compute normalized cross-correlation
    let sumA = 0, sumB = 0;
    for (let i = 0; i < overlap; i++) {
      sumA += aBrightness[aStart + i];
      sumB += bBrightness[i];
    }
    const meanA = sumA / overlap;
    const meanB = sumB / overlap;

    let num = 0, denomA = 0, denomB = 0;
    for (let i = 0; i < overlap; i++) {
      const da = aBrightness[aStart + i] - meanA;
      const db = bBrightness[i] - meanB;
      num += da * db;
      denomA += da * da;
      denomB += db * db;
    }

    const denom = Math.sqrt(denomA * denomB);
    // If either signal is uniform (zero variance), skip — correlation is undefined
    if (denom < 1e-6) continue;

    const ncc = num / denom;

    if (ncc > bestScore) {
      bestScore = ncc;
      bestOffset = overlap;
    }
  }

  // Threshold: require NCC > 0.7 for a valid match
  const CONFIDENCE_THRESHOLD = 0.7;
  if (bestScore < CONFIDENCE_THRESHOLD) {
    return null;
  }

  return { offset: bestOffset, confidence: bestScore };
}
```

- [ ] **Step 4: Run stitch tests**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/stitch.test.mjs`
Expected: The `findStitchOffset` tests pass. The `stitchImages` test fails (not yet implemented).

- [ ] **Step 5: Implement `stitchImages` in `js/image-processing.js`**

Add to the end of `js/image-processing.js`:

```js
/**
 * Stitch multiple images vertically using brightness-correlation overlap detection.
 * images: array of { canvas, brightness } objects, ordered top-to-bottom.
 *   - canvas: an OffscreenCanvas or HTMLCanvasElement with the image drawn
 *   - brightness: Float32Array from getRowBrightness()
 * Returns { canvas, warnings } where:
 *   - canvas: the stitched result as a canvas element
 *   - warnings: array of strings for any images where overlap detection failed
 */
export function stitchImages(images) {
  if (images.length === 0) return { canvas: null, warnings: ['No images provided'] };
  if (images.length === 1) return { canvas: images[0].canvas, warnings: [] };

  const warnings = [];
  const offsets = [0]; // cumulative Y offset for each image
  let totalHeight = images[0].canvas.height;
  const width = images[0].canvas.width;

  for (let i = 1; i < images.length; i++) {
    const result = findStitchOffset(images[i - 1].brightness, images[i].brightness);
    let overlap = 0;
    if (result !== null) {
      overlap = result.offset;
    } else {
      warnings.push(`Low confidence matching photos ${i} and ${i + 1}. They may not overlap enough.`);
    }
    totalHeight += images[i].canvas.height - overlap;
    offsets.push(totalHeight - images[i].canvas.height);
  }

  const outCanvas = document.createElement('canvas');
  outCanvas.width = width;
  outCanvas.height = totalHeight;
  const ctx = outCanvas.getContext('2d');

  for (let i = 0; i < images.length; i++) {
    const img = images[i].canvas;
    const y = offsets[i];

    if (i > 0) {
      // Blend the overlap region with the previous image using linear fade
      const prevBottom = offsets[i - 1] + images[i - 1].canvas.height;
      const overlapHeight = prevBottom - y;

      if (overlapHeight > 0) {
        // Draw non-overlapping top portion of this image is already handled below
        // For overlap region, use globalAlpha fade
        for (let row = 0; row < overlapHeight; row++) {
          const alpha = row / overlapHeight; // 0 at top of overlap (favor prev) → 1 at bottom (favor current)
          ctx.globalAlpha = alpha;
          ctx.drawImage(img, 0, row, width, 1, 0, y + row, width, 1);
        }
        ctx.globalAlpha = 1;
        // Draw the rest of this image below the overlap
        const remainY = overlapHeight;
        const remainH = img.height - remainY;
        if (remainH > 0) {
          ctx.drawImage(img, 0, remainY, width, remainH, 0, y + remainY, width, remainH);
        }
      } else {
        ctx.drawImage(img, 0, 0, width, img.height, 0, y, width, img.height);
      }
    } else {
      // First image: draw fully
      ctx.drawImage(img, 0, 0, width, img.height, 0, y, width, img.height);
    }
  }

  return { canvas: outCanvas, warnings };
}
```

- [ ] **Step 6: Run all tests**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/`
Expected: All tests pass (autocrop, stitch, existing).

Note: `stitchImages` depends on DOM canvas so it can't be fully unit tested in Node. The `findStitchOffset` tests cover the core algorithm. `stitchImages` will be tested manually in the browser and via integration in Task 6.

- [ ] **Step 7: Commit**

```bash
git add js/image-processing.js tests/stitch.test.mjs
git commit -m "feat: add stitching algorithm with brightness-correlation overlap detection"
```

---

### Task 4: Capture Session UI

Replace the single-shot capture UI with a multi-photo session.

**Files:**
- Create: `js/capture-session.js`
- Modify: `index.html` (new capture session HTML + wire up capture-session.js)

- [ ] **Step 1: Create `js/capture-session.js`**

```js
// js/capture-session.js

import { getRowBrightness, autoCrop } from './image-processing.js';

/**
 * Manages a capture session: collecting, auto-cropping, reordering, and removing photos.
 * Emits events via callbacks for UI updates.
 */
export class CaptureSession {
  constructor() {
    this.photos = []; // Array of { id, originalImg, croppedCanvas, brightness, fileName }
    this.nextId = 1;
    this.onChange = null; // callback() when photos array changes
  }

  /**
   * Add a photo (File or Image) to the session.
   * Returns a promise that resolves to { id, croppedCanvas, warning? }
   */
  async addPhoto(file) {
    const img = await this._loadImage(file);
    const { croppedCanvas, usedOriginal } = this._autoCropImage(img);
    const brightness = getRowBrightness(croppedCanvas);

    const photo = {
      id: this.nextId++,
      originalImg: img,
      croppedCanvas,
      brightness,
      fileName: file.name,
    };

    this.photos.push(photo);
    if (this.onChange) this.onChange();

    return {
      id: photo.id,
      croppedCanvas,
      warning: usedOriginal ? null : undefined,
    };
  }

  /**
   * Remove a photo by id.
   */
  removePhoto(id) {
    this.photos = this.photos.filter(p => p.id !== id);
    if (this.onChange) this.onChange();
  }

  /**
   * Reorder: move photo from index `from` to index `to`.
   */
  reorder(fromIndex, toIndex) {
    const [photo] = this.photos.splice(fromIndex, 1);
    this.photos.splice(toIndex, 0, photo);
    if (this.onChange) this.onChange();
  }

  /**
   * Use original (un-cropped) image for a photo, overriding auto-crop.
   */
  useOriginal(id) {
    const photo = this.photos.find(p => p.id === id);
    if (!photo) return;

    const canvas = document.createElement('canvas');
    canvas.width = photo.originalImg.naturalWidth;
    canvas.height = photo.originalImg.naturalHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(photo.originalImg, 0, 0);

    photo.croppedCanvas = canvas;
    photo.brightness = getRowBrightness(canvas);
    if (this.onChange) this.onChange();
  }

  /**
   * Reset the session, clearing all photos.
   */
  clear() {
    this.photos = [];
    this.nextId = 1;
    if (this.onChange) this.onChange();
  }

  /**
   * Get the photos array (for stitching).
   * Returns array of { canvas, brightness }.
   */
  getStitchInput() {
    return this.photos.map(p => ({
      canvas: p.croppedCanvas,
      brightness: p.brightness,
    }));
  }

  // ─── Private ─────────────────────────────────────────────────────────────

  _loadImage(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = e => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('Failed to load image'));
        img.src = e.target.result;
      };
      reader.onerror = () => reject(new Error('Failed to read file'));
      reader.readAsDataURL(file);
    });
  }

  _autoCropImage(img) {
    // Draw to canvas for pixel access
    const srcCanvas = document.createElement('canvas');
    srcCanvas.width = img.naturalWidth;
    srcCanvas.height = img.naturalHeight;
    const srcCtx = srcCanvas.getContext('2d');
    srcCtx.drawImage(img, 0, 0);

    // Run auto-crop on downsampled version for speed
    const analysisWidth = Math.min(800, srcCanvas.width);
    const scale = analysisWidth / srcCanvas.width;
    const analysisHeight = Math.round(srcCanvas.height * scale);

    const analysisCanvas = document.createElement('canvas');
    analysisCanvas.width = analysisWidth;
    analysisCanvas.height = analysisHeight;
    const analysisCtx = analysisCanvas.getContext('2d');
    analysisCtx.drawImage(srcCanvas, 0, 0, analysisWidth, analysisHeight);

    const analysisData = analysisCtx.getImageData(0, 0, analysisWidth, analysisHeight);
    const rect = autoCrop(analysisData, 200);

    // Scale rect back to original resolution
    const ox = Math.round(rect.x / scale);
    const oy = Math.round(rect.y / scale);
    const ow = Math.round(rect.w / scale);
    const oh = Math.round(rect.h / scale);

    // Check if crop is essentially the full image
    const usedOriginal = (ox === 0 && oy === 0 && ow >= srcCanvas.width - 2 && oh >= srcCanvas.height - 2);

    // Crop from original full-resolution canvas
    const croppedCanvas = document.createElement('canvas');
    croppedCanvas.width = ow;
    croppedCanvas.height = oh;
    const croppedCtx = croppedCanvas.getContext('2d');
    croppedCtx.drawImage(srcCanvas, ox, oy, ow, oh, 0, 0, ow, oh);

    // Clean up analysis canvas
    analysisCanvas.width = 0;
    analysisCanvas.height = 0;
    srcCanvas.width = 0;
    srcCanvas.height = 0;

    return { croppedCanvas, usedOriginal };
  }
}
```

- [ ] **Step 2: Update `index.html` with capture session UI**

Replace the upload area card, preview section, and the upload/preview-related JS in `index.html`. The full updated HTML body (between `<main>` tags) becomes:

```html
  <main>
    <!-- Upload area (initial screen) -->
    <div class="card" id="upload-card">
      <div id="upload-area">
        <span class="upload-icon">🧾</span>
        <p class="upload-hint">Drag &amp; drop receipt images, or use the buttons below</p>
        <div class="btn-group">
          <button class="btn btn-primary" id="btn-camera">📷 Take Photo</button>
          <button class="btn btn-secondary" id="btn-file">📁 Upload File</button>
        </div>
      </div>
      <input type="file" id="input-camera" accept="image/*" capture="environment" />
      <input type="file" id="input-file" accept="image/jpeg,image/png,image/webp,image/heic" multiple />
    </div>

    <!-- Capture session -->
    <div class="card" id="session-section" style="display:none">
      <h2>Capture Session</h2>
      <p class="session-tip" id="session-tip">Tip: For long receipts, take overlapping photos from top to bottom.</p>
      <div id="photo-list"></div>
      <div class="btn-group" style="margin-top:14px">
        <button class="btn btn-secondary" id="btn-add-photo">📷 Add Photo</button>
        <button class="btn btn-secondary" id="btn-add-file">📁 Add File</button>
      </div>
      <div class="btn-group" style="margin-top:10px">
        <button class="btn btn-primary" id="btn-done" disabled>Done - Stitch &amp; Convert</button>
        <button class="btn btn-secondary" id="btn-cancel-session">Cancel</button>
      </div>
    </div>

    <!-- Stitch preview -->
    <div class="card" id="stitch-preview-section" style="display:none">
      <h2>Stitched Preview</h2>
      <div id="stitch-warnings"></div>
      <div id="stitch-preview-container" style="max-height:400px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;margin-bottom:14px">
        <img id="stitch-preview-img" style="width:100%;display:block" />
      </div>
      <div class="btn-group">
        <button class="btn btn-primary" id="btn-convert">Convert to PDF</button>
        <button class="btn btn-secondary" id="btn-back-to-session">Back to Session</button>
      </div>
    </div>

    <!-- Progress section -->
    <div class="card" id="progress-section" style="display:none">
      <h2>Processing…</h2>
      <div class="progress-bar-wrap">
        <div class="progress-bar" id="progress-bar"></div>
      </div>
      <p class="progress-text" id="progress-text">Starting…</p>
    </div>

    <!-- Result section -->
    <div class="card" id="result-section" style="display:none">
      <h2>PDF Ready</h2>
      <div class="btn-group">
        <button class="btn btn-success" id="btn-download">⬇️ Download PDF</button>
        <button class="btn btn-secondary" id="btn-print">🖨️ Print</button>
      </div>
      <p class="result-info" id="result-info"></p>
    </div>

    <!-- Reset link -->
    <div id="reset-link" style="display:none">
      <a id="btn-reset" href="#">Process another receipt</a>
    </div>
  </main>
```

Add these CSS rules inside the existing `<style>` block:

```css
    /* Capture session */
    .session-tip {
      color: var(--text-muted);
      font-size: 0.85rem;
      margin-bottom: 14px;
    }

    .photo-item {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-bottom: 8px;
      background: var(--bg);
      cursor: grab;
    }

    .photo-item:active {
      cursor: grabbing;
    }

    .photo-item img {
      width: 60px;
      height: 80px;
      object-fit: cover;
      border-radius: 4px;
      border: 1px solid var(--border);
    }

    .photo-item .photo-info {
      flex: 1;
      font-size: 0.85rem;
      color: var(--text-muted);
    }

    .photo-item .photo-number {
      font-weight: 600;
      color: var(--text);
      font-size: 0.95rem;
    }

    .photo-item .btn-remove {
      background: none;
      border: none;
      color: #ef4444;
      font-size: 1.2rem;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 4px;
    }

    .photo-item .btn-remove:hover {
      background: #fee2e2;
    }

    .photo-item .btn-use-original {
      background: none;
      border: 1px solid var(--border);
      color: var(--text-muted);
      font-size: 0.75rem;
      cursor: pointer;
      padding: 2px 8px;
      border-radius: 4px;
    }

    .stitch-warning {
      background: #fef3c7;
      border: 1px solid #f59e0b;
      border-radius: 8px;
      padding: 10px 14px;
      margin-bottom: 10px;
      font-size: 0.85rem;
      color: #92400e;
    }
```

- [ ] **Step 3: Update the `<script>` block in `index.html` to wire up the session**

Replace the entire `<script type="module">` block with:

```html
  <script type="module">
    import { CaptureSession } from './js/capture-session.js';
    import { stitchImages, getRowBrightness } from './js/image-processing.js';
    import { generatePdf } from './js/pdf-generator.js';

    // ─── State ───────────────────────────────────────────────────────────────
    const session = new CaptureSession();
    let stitchedImage = null; // HTMLImageElement of the stitched composite
    let generatedPdfUrl = null;

    // ─── DOM refs ────────────────────────────────────────────────────────────
    const uploadCard = document.getElementById('upload-card');
    const uploadArea = document.getElementById('upload-area');
    const inputCamera = document.getElementById('input-camera');
    const inputFile = document.getElementById('input-file');
    const btnCamera = document.getElementById('btn-camera');
    const btnFile = document.getElementById('btn-file');

    const sessionSection = document.getElementById('session-section');
    const photoList = document.getElementById('photo-list');
    const btnAddPhoto = document.getElementById('btn-add-photo');
    const btnAddFile = document.getElementById('btn-add-file');
    const btnDone = document.getElementById('btn-done');
    const btnCancelSession = document.getElementById('btn-cancel-session');

    const stitchPreviewSection = document.getElementById('stitch-preview-section');
    const stitchWarnings = document.getElementById('stitch-warnings');
    const stitchPreviewImg = document.getElementById('stitch-preview-img');
    const btnConvert = document.getElementById('btn-convert');
    const btnBackToSession = document.getElementById('btn-back-to-session');

    const progressSection = document.getElementById('progress-section');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');

    const resultSection = document.getElementById('result-section');
    const resultInfo = document.getElementById('result-info');
    const btnDownload = document.getElementById('btn-download');
    const btnPrint = document.getElementById('btn-print');
    const resetLink = document.getElementById('reset-link');
    const btnReset = document.getElementById('btn-reset');

    // Hidden inputs for "Add Photo" / "Add File" in session
    const inputAddCamera = document.createElement('input');
    inputAddCamera.type = 'file';
    inputAddCamera.accept = 'image/*';
    inputAddCamera.setAttribute('capture', 'environment');
    document.body.appendChild(inputAddCamera);

    const inputAddFile = document.createElement('input');
    inputAddFile.type = 'file';
    inputAddFile.accept = 'image/jpeg,image/png,image/webp,image/heic';
    inputAddFile.multiple = true;
    document.body.appendChild(inputAddFile);

    // ─── Helper ──────────────────────────────────────────────────────────────
    function formatBytes(bytes) {
      if (bytes < 1024) return bytes + ' B';
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function showSection(section) {
      [uploadCard, sessionSection, stitchPreviewSection, progressSection, resultSection].forEach(s => {
        s.style.display = 'none';
      });
      resetLink.style.display = 'none';
      section.style.display = 'block';
    }

    // ─── Upload → Start Session ──────────────────────────────────────────────
    btnCamera.addEventListener('click', () => inputCamera.click());
    btnFile.addEventListener('click', () => inputFile.click());

    inputCamera.addEventListener('change', async e => {
      if (e.target.files[0]) {
        showSection(sessionSection);
        await session.addPhoto(e.target.files[0]);
        inputCamera.value = '';
      }
    });

    inputFile.addEventListener('change', async e => {
      if (e.target.files.length > 0) {
        showSection(sessionSection);
        for (const file of e.target.files) {
          await session.addPhoto(file);
        }
        inputFile.value = '';
      }
    });

    // Drag and drop
    uploadArea.addEventListener('dragover', e => {
      e.preventDefault();
      uploadArea.classList.add('drag-over');
    });
    uploadArea.addEventListener('dragleave', () => {
      uploadArea.classList.remove('drag-over');
    });
    uploadArea.addEventListener('drop', async e => {
      e.preventDefault();
      uploadArea.classList.remove('drag-over');
      const files = [...e.dataTransfer.files].filter(f => f.type.startsWith('image/'));
      if (files.length > 0) {
        showSection(sessionSection);
        for (const file of files) {
          await session.addPhoto(file);
        }
      }
    });

    // ─── Session: Add More Photos ────────────────────────────────────────────
    btnAddPhoto.addEventListener('click', () => inputAddCamera.click());
    btnAddFile.addEventListener('click', () => inputAddFile.click());

    inputAddCamera.addEventListener('change', async e => {
      if (e.target.files[0]) {
        await session.addPhoto(e.target.files[0]);
        inputAddCamera.value = '';
      }
    });

    inputAddFile.addEventListener('change', async e => {
      for (const file of e.target.files) {
        await session.addPhoto(file);
      }
      inputAddFile.value = '';
    });

    // ─── Session: Render Photo List ──────────────────────────────────────────
    session.onChange = () => {
      renderPhotoList();
      btnDone.disabled = session.photos.length === 0;
    };

    function renderPhotoList() {
      photoList.innerHTML = '';
      session.photos.forEach((photo, index) => {
        const item = document.createElement('div');
        item.className = 'photo-item';
        item.draggable = true;
        item.dataset.index = index;

        const thumb = document.createElement('img');
        thumb.src = photo.croppedCanvas.toDataURL('image/jpeg', 0.5);
        thumb.alt = `Photo ${index + 1}`;

        const info = document.createElement('div');
        info.className = 'photo-info';
        info.innerHTML = `<div class="photo-number">#${index + 1}</div>
          <div>${photo.croppedCanvas.width} × ${photo.croppedCanvas.height} px</div>`;

        const useOrigBtn = document.createElement('button');
        useOrigBtn.className = 'btn-use-original';
        useOrigBtn.textContent = 'Use Original';
        useOrigBtn.addEventListener('click', () => {
          session.useOriginal(photo.id);
        });

        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn-remove';
        removeBtn.textContent = '✕';
        removeBtn.title = 'Remove this photo';
        removeBtn.addEventListener('click', () => {
          session.removePhoto(photo.id);
        });

        item.appendChild(thumb);
        item.appendChild(info);
        item.appendChild(useOrigBtn);
        item.appendChild(removeBtn);

        // Drag-and-drop reorder
        item.addEventListener('dragstart', e => {
          e.dataTransfer.setData('text/plain', index.toString());
          item.style.opacity = '0.5';
        });
        item.addEventListener('dragend', () => {
          item.style.opacity = '1';
        });
        item.addEventListener('dragover', e => {
          e.preventDefault();
          item.style.borderColor = 'var(--primary)';
        });
        item.addEventListener('dragleave', () => {
          item.style.borderColor = 'var(--border)';
        });
        item.addEventListener('drop', e => {
          e.preventDefault();
          item.style.borderColor = 'var(--border)';
          const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
          const toIndex = index;
          if (fromIndex !== toIndex) {
            session.reorder(fromIndex, toIndex);
          }
        });

        photoList.appendChild(item);
      });
    }

    // ─── Session: Done → Stitch ──────────────────────────────────────────────
    btnDone.addEventListener('click', async () => {
      const input = session.getStitchInput();

      if (input.length === 1) {
        // Single photo — skip stitching, go straight to convert
        const canvas = input[0].canvas;
        const img = new Image();
        img.onload = () => {
          stitchedImage = img;
          stitchPreviewImg.src = img.src;
          stitchWarnings.innerHTML = '';
          showSection(stitchPreviewSection);
        };
        img.src = canvas.toDataURL('image/jpeg', 0.92);
        return;
      }

      // Multiple photos — stitch
      btnDone.disabled = true;
      btnDone.textContent = 'Stitching…';

      try {
        const result = stitchImages(input);

        stitchWarnings.innerHTML = '';
        for (const warning of result.warnings) {
          const div = document.createElement('div');
          div.className = 'stitch-warning';
          div.textContent = warning;
          stitchWarnings.appendChild(div);
        }

        const img = new Image();
        img.onload = () => {
          stitchedImage = img;
          stitchPreviewImg.src = img.src;
          showSection(stitchPreviewSection);
        };
        img.src = result.canvas.toDataURL('image/jpeg', 0.92);
      } finally {
        btnDone.disabled = false;
        btnDone.textContent = 'Done - Stitch & Convert';
      }
    });

    btnBackToSession.addEventListener('click', () => {
      showSection(sessionSection);
    });

    btnCancelSession.addEventListener('click', () => {
      session.clear();
      stitchedImage = null;
      showSection(uploadCard);
    });

    // ─── Convert to PDF ──────────────────────────────────────────────────────
    function updateProgress(text, percent) {
      progressText.textContent = text;
      progressBar.style.width = percent + '%';
    }

    btnConvert.addEventListener('click', async () => {
      if (!stitchedImage) return;
      showSection(progressSection);

      try {
        const result = await generatePdf(stitchedImage, updateProgress);

        if (generatedPdfUrl) URL.revokeObjectURL(generatedPdfUrl);
        generatedPdfUrl = result.blobUrl;

        updateProgress('Done!', 100);
        await new Promise(r => setTimeout(r, 200));

        showSection(resultSection);
        resetLink.style.display = 'block';

        const firstName = session.photos[0]?.fileName || 'receipt';
        resultInfo.textContent =
          `${result.numPages} page${result.numPages !== 1 ? 's' : ''} · ` +
          `${result.numStrips} strip${result.numStrips !== 1 ? 's' : ''} · ` +
          `${result.colsPerPage} column${result.colsPerPage !== 1 ? 's' : ''} per page`;
      } catch (err) {
        console.error('PDF generation failed:', err);
        showSection(stitchPreviewSection);
        alert('An error occurred while generating the PDF. Please try again.');
      }
    });

    // ─── Download & Print ────────────────────────────────────────────────────
    btnDownload.addEventListener('click', () => {
      if (!generatedPdfUrl) return;
      const firstName = session.photos[0]?.fileName?.replace(/\.[^.]+$/, '') || 'receipt';
      const a = document.createElement('a');
      a.href = generatedPdfUrl;
      a.download = `receipt_${firstName}_letter.pdf`;
      a.click();
    });

    btnPrint.addEventListener('click', () => {
      if (!generatedPdfUrl) return;
      const printWindow = window.open(generatedPdfUrl);
      if (printWindow) {
        printWindow.addEventListener('load', () => printWindow.print());
      }
    });

    // ─── Reset ───────────────────────────────────────────────────────────────
    btnReset.addEventListener('click', e => {
      e.preventDefault();
      session.clear();
      stitchedImage = null;
      if (generatedPdfUrl) {
        URL.revokeObjectURL(generatedPdfUrl);
        generatedPdfUrl = null;
      }
      progressBar.style.width = '0%';
      progressText.textContent = 'Starting…';
      resultInfo.textContent = '';
      showSection(uploadCard);
    });
  </script>
```

- [ ] **Step 4: Test manually in browser**

Open `index.html` via a local HTTP server (required for ES module imports):

Run: `cd /home/drobinson911/receipt-cutter && npx serve .`

Then open the URL in a browser and verify:
1. Camera button opens camera / file picker
2. Upload button opens file picker (now accepts multiple files)
3. Photos appear as thumbnails in the session
4. Remove button removes a photo
5. "Use Original" button resets auto-crop
6. "Done" with 1 photo goes to preview
7. "Cancel" returns to upload screen

- [ ] **Step 5: Commit**

```bash
git add js/capture-session.js index.html
git commit -m "feat: add multi-photo capture session UI with auto-crop"
```

---

### Task 5: PWA Support

Add manifest.json, service worker, and app icons for installable web app.

**Files:**
- Create: `manifest.json`
- Create: `sw.js`
- Create: `icons/icon-192.png` (generated via canvas in a build step, or placeholder SVG)
- Create: `icons/icon-512.png`
- Modify: `index.html` (add manifest link, theme-color meta, SW registration)

- [ ] **Step 1: Create `manifest.json`**

```json
{
  "name": "Receipt Cutter",
  "short_name": "Receipt Cutter",
  "description": "Slice long receipts into strips and save as letter-size PDF",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#f8fafc",
  "theme_color": "#2563eb",
  "icons": [
    {
      "src": "icons/icon-192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any maskable"
    },
    {
      "src": "icons/icon-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "any maskable"
    }
  ]
}
```

- [ ] **Step 2: Create `sw.js`**

```js
const CACHE_NAME = 'receipt-cutter-v1';
const ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/js/image-processing.js',
  '/js/pdf-generator.js',
  '/js/capture-session.js',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.2/jspdf.umd.min.js',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(cached => cached || fetch(event.request))
  );
});
```

- [ ] **Step 3: Generate app icons using a Node script**

Create and run a one-time script to generate simple receipt-emoji icons:

```bash
cd /home/drobinson911/receipt-cutter && mkdir -p icons
node -e "
const { createCanvas } = require('canvas');

function makeIcon(size, path) {
  const c = createCanvas(size, size);
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#2563eb';
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = '#ffffff';
  ctx.font = Math.round(size * 0.6) + 'px serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('🧾', size/2, size/2);
  const fs = require('fs');
  fs.writeFileSync(path, c.toBuffer('image/png'));
}

makeIcon(192, 'icons/icon-192.png');
makeIcon(512, 'icons/icon-512.png');
console.log('Icons generated');
"
```

Note: If `canvas` npm package is not available, create simple placeholder icons using an SVG-to-PNG approach or manually create minimal PNG files. The icons can be improved later. A minimal fallback:

```bash
cd /home/drobinson911/receipt-cutter && mkdir -p icons
# Create minimal 1x1 blue PNG as placeholder (will be replaced with proper icons)
node -e "
const fs = require('fs');
// Minimal valid PNG: 1x1 blue pixel, then we'll use SVG icons instead
// For now, create SVG icons that browsers can use
const svg192 = '<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"192\" height=\"192\" viewBox=\"0 0 192 192\"><rect width=\"192\" height=\"192\" fill=\"#2563eb\" rx=\"24\"/><text x=\"96\" y=\"110\" text-anchor=\"middle\" font-size=\"100\">🧾</text></svg>';
const svg512 = '<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"512\" height=\"512\" viewBox=\"0 0 512 512\"><rect width=\"512\" height=\"512\" fill=\"#2563eb\" rx=\"64\"/><text x=\"256\" y=\"300\" text-anchor=\"middle\" font-size=\"280\">🧾</text></svg>';
fs.writeFileSync('icons/icon-192.svg', svg192);
fs.writeFileSync('icons/icon-512.svg', svg512);
console.log('SVG icons created');
"
```

If using SVG, update `manifest.json` icon entries to use `.svg` extension and `"type": "image/svg+xml"`.

- [ ] **Step 4: Add PWA meta tags and SW registration to `index.html`**

Add these inside `<head>`, after the `<title>` tag:

```html
  <link rel="manifest" href="manifest.json" />
  <meta name="theme-color" content="#2563eb" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="default" />
  <link rel="apple-touch-icon" href="icons/icon-192.png" />
```

Add SW registration at the very end of `<body>`, after the closing `</script>` of the main module:

```html
  <script>
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('sw.js');
    }
  </script>
```

- [ ] **Step 5: Test PWA installation**

Run: `cd /home/drobinson911/receipt-cutter && npx serve .`

In Chrome:
1. Open DevTools → Application → Manifest — verify manifest loads correctly
2. Application → Service Workers — verify SW is registered
3. Look for install prompt in address bar (desktop) or "Add to Home Screen" (mobile)

- [ ] **Step 6: Commit**

```bash
git add manifest.json sw.js icons/ index.html
git commit -m "feat: add PWA support with manifest, service worker, and app icons"
```

---

### Task 6: Integration Testing and Polish

End-to-end manual testing and bug fixes.

**Files:**
- Potentially any file from Tasks 1-5

- [ ] **Step 1: Test single-photo flow**

1. Open app in browser via `npx serve .`
2. Take or upload a single receipt photo
3. Verify auto-crop removes background
4. Click "Done" → verify it goes to stitch preview with just the one image
5. Click "Convert to PDF" → verify PDF generates correctly
6. Download and open PDF → verify receipt strips are properly laid out

- [ ] **Step 2: Test multi-photo stitching flow**

1. Take 3+ overlapping photos of a long receipt (or use pre-taken photos)
2. Verify each photo appears in the session list with thumbnail
3. Verify reorder works (drag a photo to a different position)
4. Verify remove works (click ✕ on a photo)
5. Click "Done" → verify stitch preview shows a combined tall receipt
6. If warnings appear, verify they make sense
7. Click "Convert to PDF" → verify PDF is correct

- [ ] **Step 3: Test error recovery flows**

1. "Cancel" during session → returns to upload screen
2. "Back to Session" from stitch preview → returns to session with photos intact
3. "Use Original" on a photo → verify it shows the uncropped version
4. Upload a non-receipt image → verify auto-crop fallback (full image)
5. "Process another receipt" after PDF → full reset

- [ ] **Step 4: Test PWA installation**

1. On phone browser, verify "Add to Home Screen" works
2. Open installed PWA → verify it works offline (after first load)
3. On desktop Chrome, verify install icon appears in address bar

- [ ] **Step 5: Fix any issues found and commit**

```bash
git add -A
git commit -m "fix: address integration testing issues"
```

- [ ] **Step 6: Run all unit tests one final time**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/`
Expected: All tests pass.

- [ ] **Step 7: Final commit if any remaining changes**

```bash
git add -A
git commit -m "chore: final polish after integration testing"
```
