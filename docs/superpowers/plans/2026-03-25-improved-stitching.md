# Improved Stitching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 1D brightness stitching with 2D block matching that handles scale differences and horizontal shift, plus a stack-only fallback mode.

**Architecture:** Add `normalizeScales()`, `findStitchOffset2D()`, and `stackImages()` to `image-processing.js`. Rewrite `stitchImages()` to use these. The old `findStitchOffset()` is removed. `capture-session.js` gets a `stitchMode` property. `index.html` gets a stitch mode toggle. The 2D matching uses normalized cross-correlation on image patches (not brightness arrays), with a coarse-to-fine search strategy.

**Tech Stack:** Vanilla JS, Canvas API, ImageData pixel access for NCC computation.

---

## File Structure

```
js/
  image-processing.js    (modified — replace findStitchOffset/stitchImages, add normalizeScales/findStitchOffset2D/stackImages)
  capture-session.js     (modified — add stitchMode property)
  pdf-generator.js       (no changes)
  camera-viewfinder.js   (no changes)
index.html               (modified — stitch mode toggle, updated warning display)
tests/
  stitch.test.mjs        (replaced — new tests for 2D matching and scale normalization)
  autocrop.test.mjs      (no changes)
  receipt-cutter.test.mjs (no changes)
```

---

### Task 1: Scale Normalization

Add a function to normalize all images to the same receipt width.

**Files:**
- Modify: `js/image-processing.js`
- Create: `tests/stitch.test.mjs` (replace existing)

- [ ] **Step 1: Write failing tests for `normalizeScales`**

Replace `tests/stitch.test.mjs` entirely with:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeScales } from '../js/image-processing.js';

/**
 * Create a mock image object with width/height and pixel data.
 * Simulates a canvas with getContext/getImageData/drawImage by using
 * a plain { width, height, data } structure for testing pure logic.
 */
function makeMockImageData(width, height, pattern = 'gradient') {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      let v;
      if (pattern === 'gradient') {
        v = ((x + y * 3) * 7 + 13) % 256;
      } else {
        v = 128;
      }
      data[i] = v;
      data[i + 1] = v;
      data[i + 2] = v;
      data[i + 3] = 255;
    }
  }
  return { width, height, data };
}

test('normalizeScales: returns target width as median of input widths', () => {
  const result = normalizeScales([
    { width: 600, height: 800 },
    { width: 800, height: 1000 },
    { width: 700, height: 900 },
  ]);
  // Median of [600, 700, 800] = 700
  assert.equal(result.targetWidth, 700);
});

test('normalizeScales: computes correct scale factors', () => {
  const result = normalizeScales([
    { width: 600, height: 800 },
    { width: 800, height: 1000 },
    { width: 700, height: 900 },
  ]);
  // targetWidth = 700
  // factors: 700/600 ≈ 1.167, 700/800 = 0.875, 700/700 = 1.0
  assert.ok(Math.abs(result.scaleFactors[0] - 700/600) < 0.001);
  assert.ok(Math.abs(result.scaleFactors[1] - 700/800) < 0.001);
  assert.equal(result.scaleFactors[2], 1);
});

test('normalizeScales: computes correct scaled dimensions', () => {
  const result = normalizeScales([
    { width: 600, height: 800 },
    { width: 800, height: 1000 },
    { width: 700, height: 900 },
  ]);
  // All widths should be 700
  // Heights: round(800 * 700/600) = 933, round(1000 * 700/800) = 875, 900
  assert.deepEqual(result.scaledDimensions, [
    { width: 700, height: Math.round(800 * 700/600) },
    { width: 700, height: Math.round(1000 * 700/800) },
    { width: 700, height: 900 },
  ]);
});

test('normalizeScales: single image returns scale factor 1', () => {
  const result = normalizeScales([{ width: 500, height: 600 }]);
  assert.equal(result.targetWidth, 500);
  assert.deepEqual(result.scaleFactors, [1]);
  assert.deepEqual(result.scaledDimensions, [{ width: 500, height: 600 }]);
});

test('normalizeScales: identical widths returns all scale factors 1', () => {
  const result = normalizeScales([
    { width: 800, height: 1000 },
    { width: 800, height: 900 },
    { width: 800, height: 1100 },
  ]);
  assert.equal(result.targetWidth, 800);
  assert.deepEqual(result.scaleFactors, [1, 1, 1]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/stitch.test.mjs`
Expected: FAIL — `normalizeScales` is not exported

- [ ] **Step 3: Implement `normalizeScales`**

In `js/image-processing.js`, replace the entire stitching section (from the `// ─── Stitching Functions` comment through the end of `stitchImages`) with:

```js
// ─── Stitching Functions ──────────────────────────────────────────────────

/**
 * Compute scale normalization info for a set of images.
 * Takes array of objects with { width, height } (canvas-like).
 * Returns { targetWidth, scaleFactors, scaledDimensions }.
 * Target width is the median width across all images.
 */
export function normalizeScales(images) {
  const widths = images.map(img => img.width);
  const sorted = [...widths].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const targetWidth = sorted.length % 2 === 0
    ? Math.round((sorted[mid - 1] + sorted[mid]) / 2)
    : sorted[mid];

  const scaleFactors = widths.map(w => w === targetWidth ? 1 : targetWidth / w);
  const scaledDimensions = images.map((img, i) => ({
    width: targetWidth,
    height: Math.round(img.height * scaleFactors[i]),
  }));

  return { targetWidth, scaleFactors, scaledDimensions };
}
```

Note: This removes `findStitchOffset` and `stitchImages` temporarily. They will be replaced in Tasks 2 and 4. Tests for the old functions in `stitch.test.mjs` have already been replaced.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/stitch.test.mjs`
Expected: All 5 tests pass.

- [ ] **Step 5: Run remaining tests for regression**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/autocrop.test.mjs tests/receipt-cutter.test.mjs`
Expected: All 11 tests pass.

- [ ] **Step 6: Commit**

```bash
git add js/image-processing.js tests/stitch.test.mjs
git commit -m "feat: add normalizeScales, remove old 1D stitching functions"
```

---

### Task 2: 2D Block Matching (findStitchOffset2D)

The core 2D template matching algorithm with coarse-to-fine search.

**Files:**
- Modify: `js/image-processing.js`
- Modify: `tests/stitch.test.mjs`

- [ ] **Step 1: Add failing tests for `findStitchOffset2D`**

Append to `tests/stitch.test.mjs`:

```js
import { findStitchOffset2D } from '../js/image-processing.js';

/**
 * Create a synthetic grayscale image as { data, width, height } (ImageData-like).
 * Each pixel gets brightness from a deterministic pattern seeded by `seed`.
 */
function makeSyntheticImage(width, height, seed = 0) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const v = ((x * 7 + y * 13 + seed * 31) * 37 + 53) % 256;
      data[i] = v;
      data[i + 1] = v;
      data[i + 2] = v;
      data[i + 3] = 255;
    }
  }
  return { data, width, height };
}

/**
 * Create two images where image B's top `overlapH` rows are a copy of
 * image A's bottom `overlapH` rows, optionally shifted by shiftX pixels.
 */
function makeOverlappingPair(width, heightA, heightB, overlapH, shiftX = 0) {
  const imgA = makeSyntheticImage(width, heightA, 1);
  const imgB = makeSyntheticImage(width, heightB, 2);

  // Copy bottom overlapH rows of A into top overlapH rows of B, shifted by shiftX
  for (let y = 0; y < overlapH; y++) {
    for (let x = 0; x < width; x++) {
      const srcX = x - shiftX;
      if (srcX < 0 || srcX >= width) continue;
      const srcI = ((heightA - overlapH + y) * width + srcX) * 4;
      const dstI = (y * width + x) * 4;
      imgB.data[dstI] = imgA.data[srcI];
      imgB.data[dstI + 1] = imgA.data[srcI + 1];
      imgB.data[dstI + 2] = imgA.data[srcI + 2];
      imgB.data[dstI + 3] = 255;
    }
  }

  return { imgA, imgB };
}

test('findStitchOffset2D: detects exact vertical overlap', () => {
  const { imgA, imgB } = makeOverlappingPair(200, 400, 400, 80, 0);
  const result = findStitchOffset2D(imgA, imgB);

  assert.ok(result !== null, 'Should find a match');
  assert.ok(Math.abs(result.offsetY - 80) <= 4, `offsetY=${result.offsetY} should be near 80`);
  assert.ok(Math.abs(result.offsetX) <= 4, `offsetX=${result.offsetX} should be near 0`);
  assert.ok(result.confidence > 0.6, `confidence=${result.confidence}`);
});

test('findStitchOffset2D: detects overlap with horizontal shift', () => {
  const { imgA, imgB } = makeOverlappingPair(200, 400, 400, 80, 10);
  const result = findStitchOffset2D(imgA, imgB);

  assert.ok(result !== null, 'Should find a match');
  assert.ok(Math.abs(result.offsetY - 80) <= 4, `offsetY=${result.offsetY} should be near 80`);
  assert.ok(Math.abs(result.offsetX - 10) <= 4, `offsetX=${result.offsetX} should be near 10`);
  assert.ok(result.confidence > 0.6, `confidence=${result.confidence}`);
});

test('findStitchOffset2D: returns null for non-overlapping images', () => {
  const imgA = makeSyntheticImage(200, 400, 1);
  const imgB = makeSyntheticImage(200, 400, 99);
  const result = findStitchOffset2D(imgA, imgB);

  assert.equal(result, null, 'Should return null for non-overlapping images');
});

test('findStitchOffset2D: handles noisy overlap', () => {
  const { imgA, imgB } = makeOverlappingPair(200, 400, 400, 80, 0);
  // Add deterministic noise to imgB's overlap region
  for (let y = 0; y < 80; y++) {
    for (let x = 0; x < 200; x++) {
      const i = (y * 200 + x) * 4;
      const noise = Math.round(Math.sin(x * 13 + y * 7) * 8);
      imgB.data[i] = Math.max(0, Math.min(255, imgB.data[i] + noise));
      imgB.data[i + 1] = imgB.data[i];
      imgB.data[i + 2] = imgB.data[i];
    }
  }

  const result = findStitchOffset2D(imgA, imgB);

  assert.ok(result !== null, 'Should find match despite noise');
  assert.ok(Math.abs(result.offsetY - 80) <= 4, `offsetY=${result.offsetY} should be near 80`);
  assert.ok(result.confidence > 0.5, `confidence=${result.confidence}`);
});
```

Also update the import at line 3 to include `findStitchOffset2D`:

```js
import { normalizeScales, findStitchOffset2D } from '../js/image-processing.js';
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/stitch.test.mjs`
Expected: normalizeScales tests pass, findStitchOffset2D tests fail.

- [ ] **Step 3: Implement `findStitchOffset2D`**

Add to `js/image-processing.js` after `normalizeScales`:

```js
/**
 * Compute 2D normalized cross-correlation between a template and a patch.
 * Both are { data, width, height } ImageData-like objects.
 * template is placed at (tx, ty) within search region.
 * Uses grayscale: (R+G+B)/3.
 * Returns NCC score in range [-1, 1].
 */
function computeNCC(templateData, tW, tH, searchData, sW, sH, tx, ty) {
  let sumT = 0, sumS = 0, count = 0;

  for (let y = 0; y < tH; y++) {
    for (let x = 0; x < tW; x++) {
      const sx = tx + x;
      const sy = ty + y;
      if (sx < 0 || sx >= sW || sy < 0 || sy >= sH) continue;

      const ti = (y * tW + x) * 4;
      const si = (sy * sW + sx) * 4;
      const tVal = (templateData[ti] + templateData[ti + 1] + templateData[ti + 2]) / 3;
      const sVal = (searchData[si] + searchData[si + 1] + searchData[si + 2]) / 3;
      sumT += tVal;
      sumS += sVal;
      count++;
    }
  }

  if (count === 0) return -1;
  const meanT = sumT / count;
  const meanS = sumS / count;

  let num = 0, denomT = 0, denomS = 0;
  for (let y = 0; y < tH; y++) {
    for (let x = 0; x < tW; x++) {
      const sx = tx + x;
      const sy = ty + y;
      if (sx < 0 || sx >= sW || sy < 0 || sy >= sH) continue;

      const ti = (y * tW + x) * 4;
      const si = (sy * sW + sx) * 4;
      const tVal = (templateData[ti] + templateData[ti + 1] + templateData[ti + 2]) / 3;
      const sVal = (searchData[si] + searchData[si + 1] + searchData[si + 2]) / 3;
      const dt = tVal - meanT;
      const ds = sVal - meanS;
      num += dt * ds;
      denomT += dt * dt;
      denomS += ds * ds;
    }
  }

  const denom = Math.sqrt(denomT * denomS);
  if (denom < 1e-6) return -1;
  return num / denom;
}

/**
 * Find the 2D overlap offset between two images using template matching.
 * imgA, imgB: { data, width, height } ImageData-like objects.
 * Extracts a horizontal strip from the bottom of A and searches the top of B.
 * Uses coarse-to-fine: 2x downsample for coarse pass, full-res refinement.
 * Returns { offsetX, offsetY, confidence } or null if no good match.
 * offsetX: horizontal shift of B relative to A (positive = B shifted right)
 * offsetY: number of rows from top of B that overlap with bottom of A
 */
export function findStitchOffset2D(imgA, imgB) {
  const TEMPLATE_HEIGHT = 60;
  const SEARCH_FRAC = 0.4;
  const MAX_SHIFT_X = Math.round(imgA.width * 0.15); // max 15% horizontal shift
  const CONFIDENCE_THRESHOLD = 0.6;

  // ── Extract template: bottom strip of A ──
  const tY = imgA.height - Math.min(TEMPLATE_HEIGHT, Math.round(imgA.height * 0.15));
  const tH = imgA.height - tY;
  const tW = imgA.width;
  const templateData = new Uint8ClampedArray(tW * tH * 4);
  for (let y = 0; y < tH; y++) {
    const srcOffset = ((tY + y) * imgA.width) * 4;
    const dstOffset = (y * tW) * 4;
    templateData.set(imgA.data.subarray(srcOffset, srcOffset + tW * 4), dstOffset);
  }

  // ── Search region: top portion of B ──
  const searchH = Math.min(Math.round(imgB.height * SEARCH_FRAC), imgB.height);
  const searchW = imgB.width;
  const searchData = imgB.data; // use full B data, just limit Y range

  // ── Coarse pass: downsample 2x ──
  const cScale = 0.5;
  const cTW = Math.round(tW * cScale);
  const cTH = Math.round(tH * cScale);
  const cSW = Math.round(searchW * cScale);
  const cSH = Math.round(searchH * cScale);
  const cMaxShiftX = Math.round(MAX_SHIFT_X * cScale);

  // Simple downsample by averaging 2x2 blocks
  function downsample(srcData, srcW, srcH, dstW, dstH) {
    const dst = new Uint8ClampedArray(dstW * dstH * 4);
    for (let y = 0; y < dstH; y++) {
      for (let x = 0; x < dstW; x++) {
        const sx = Math.min(Math.round(x / cScale), srcW - 1);
        const sy = Math.min(Math.round(y / cScale), srcH - 1);
        const si = (sy * srcW + sx) * 4;
        const di = (y * dstW + x) * 4;
        dst[di] = srcData[si];
        dst[di + 1] = srcData[si + 1];
        dst[di + 2] = srcData[si + 2];
        dst[di + 3] = 255;
      }
    }
    return dst;
  }

  const cTemplate = downsample(templateData, tW, tH, cTW, cTH);
  const cSearch = downsample(searchData, imgB.width, imgB.height, cSW, Math.round(imgB.height * cScale));

  // Slide coarse template, collect top candidates
  const candidates = [];
  const stepX = 2;
  const stepY = 2;

  for (let cy = 0; cy <= cSH - cTH; cy += stepY) {
    for (let cx = -cMaxShiftX; cx <= cMaxShiftX; cx += stepX) {
      const ncc = computeNCC(cTemplate, cTW, cTH, cSearch, cSW, Math.round(imgB.height * cScale), cx, cy);
      if (ncc > 0.3) { // loose threshold for coarse candidates
        candidates.push({ x: cx, y: cy, score: ncc });
      }
    }
  }

  if (candidates.length === 0) return null;

  // Keep top 5 candidates
  candidates.sort((a, b) => b.score - a.score);
  const topCandidates = candidates.slice(0, 5);

  // ── Fine pass: search around each candidate at full resolution ──
  let bestResult = null;

  for (const c of topCandidates) {
    // Scale back to full resolution coordinates
    const fullX = Math.round(c.x / cScale);
    const fullY = Math.round(c.y / cScale);

    // Search ±4px around the candidate
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const fx = fullX + dx;
        const fy = fullY + dy;
        if (fy < 0 || fy + tH > imgB.height) continue;

        const ncc = computeNCC(templateData, tW, tH, searchData, imgB.width, imgB.height, fx, fy);
        if (bestResult === null || ncc > bestResult.confidence) {
          bestResult = {
            offsetX: fx,
            offsetY: fy + tH, // overlap = position of template match + template height
            confidence: ncc,
          };
        }
      }
    }
  }

  if (bestResult === null || bestResult.confidence < CONFIDENCE_THRESHOLD) {
    return null;
  }

  return bestResult;
}
```

- [ ] **Step 4: Run tests**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/stitch.test.mjs`
Expected: All 9 tests pass (5 normalizeScales + 4 findStitchOffset2D).

- [ ] **Step 5: Run all tests for regression**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/*.mjs`
Expected: All tests pass (stitch + autocrop + receipt-cutter).

- [ ] **Step 6: Commit**

```bash
git add js/image-processing.js tests/stitch.test.mjs
git commit -m "feat: add 2D block matching with coarse-to-fine search"
```

---

### Task 3: Stack Images Function

Simple vertical concatenation with separator lines.

**Files:**
- Modify: `js/image-processing.js`
- Modify: `tests/stitch.test.mjs`

- [ ] **Step 1: Add failing tests for `stackImages`**

Append to `tests/stitch.test.mjs`:

```js
import { stackImages } from '../js/image-processing.js';

test('stackImages: returns null for empty input', () => {
  const result = stackImages([]);
  assert.equal(result.canvas, null);
});

test('stackImages: single image returns it unchanged', () => {
  const img = makeSyntheticImage(100, 200);
  const result = stackImages([img]);
  assert.equal(result.canvas.width, 100);
  assert.equal(result.canvas.height, 200);
});

test('stackImages: two images stacked with separator', () => {
  const img1 = makeSyntheticImage(100, 200);
  const img2 = makeSyntheticImage(100, 300);
  const result = stackImages([img1, img2]);
  // height = 200 + 2 (separator) + 300 = 502
  assert.equal(result.canvas.width, 100);
  assert.equal(result.canvas.height, 502);
});

test('stackImages: three images stacked with separators', () => {
  const img1 = makeSyntheticImage(100, 100);
  const img2 = makeSyntheticImage(100, 150);
  const img3 = makeSyntheticImage(100, 200);
  const result = stackImages([img1, img2, img3]);
  // height = 100 + 2 + 150 + 2 + 200 = 454
  assert.equal(result.canvas.width, 100);
  assert.equal(result.canvas.height, 454);
});
```

Update the import to include `stackImages`:

```js
import { normalizeScales, findStitchOffset2D, stackImages } from '../js/image-processing.js';
```

Note: `stackImages` uses `document.createElement('canvas')` which isn't available in Node. For testability, the function should accept an optional `createCanvas` parameter. The tests will provide a mock canvas factory. Update the test helper section to add:

```js
/**
 * Mock canvas for Node testing. Stores draw operations as data.
 */
function createMockCanvas() {
  const canvas = {
    width: 0,
    height: 0,
    _ops: [],
    getContext() {
      return {
        fillStyle: '',
        fillRect(x, y, w, h) { canvas._ops.push({ op: 'fillRect', x, y, w, h }); },
        drawImage() { canvas._ops.push({ op: 'drawImage', args: [...arguments] }); },
        clearRect() {},
        globalAlpha: 1,
        setLineDash() {},
        beginPath() {},
        moveTo() {},
        lineTo() {},
        stroke() {},
        strokeStyle: '',
        lineWidth: 1,
      };
    },
  };
  return canvas;
}
```

And update the stackImages tests to pass the mock factory:

```js
test('stackImages: two images stacked with separator', () => {
  const img1 = makeSyntheticImage(100, 200);
  const img2 = makeSyntheticImage(100, 300);
  const result = stackImages([img1, img2], createMockCanvas);
  assert.equal(result.canvas.width, 100);
  assert.equal(result.canvas.height, 502);
});
```

(Apply the same pattern to all stackImages tests.)

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/stitch.test.mjs`
Expected: normalizeScales and findStitchOffset2D tests pass, stackImages tests fail.

- [ ] **Step 3: Implement `stackImages`**

Add to `js/image-processing.js` after `findStitchOffset2D`:

```js
/**
 * Stack images vertically with separator lines between them.
 * images: array of { data, width, height } ImageData-like objects.
 * createCanvasFn: optional factory for canvas creation (for testing).
 * Returns { canvas } where canvas has all images stacked.
 */
export function stackImages(images, createCanvasFn) {
  const _createCanvas = createCanvasFn || (() => document.createElement('canvas'));

  if (images.length === 0) return { canvas: null };
  if (images.length === 1) {
    const out = _createCanvas();
    out.width = images[0].width;
    out.height = images[0].height;
    const ctx = out.getContext('2d');
    ctx.drawImage(images[0], 0, 0);
    return { canvas: out };
  }

  const SEPARATOR_H = 2;
  const width = images[0].width;
  const totalHeight = images.reduce((sum, img) => sum + img.height, 0) + (images.length - 1) * SEPARATOR_H;

  const out = _createCanvas();
  out.width = width;
  out.height = totalHeight;
  const ctx = out.getContext('2d');

  let y = 0;
  for (let i = 0; i < images.length; i++) {
    if (i > 0) {
      // Draw separator line
      ctx.fillStyle = '#e2e8f0';
      ctx.fillRect(0, y, width, SEPARATOR_H);
      y += SEPARATOR_H;
    }
    ctx.drawImage(images[i], 0, 0, images[i].width, images[i].height, 0, y, width, images[i].height);
    y += images[i].height;
  }

  return { canvas: out };
}
```

- [ ] **Step 4: Run tests**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/stitch.test.mjs`
Expected: All 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add js/image-processing.js tests/stitch.test.mjs
git commit -m "feat: add stackImages for simple vertical concatenation with separators"
```

---

### Task 4: Rewrite stitchImages

Replace the old `stitchImages` with the new version that uses scale normalization, 2D matching, and stack fallback.

**Files:**
- Modify: `js/image-processing.js`

- [ ] **Step 1: Implement new `stitchImages`**

Add to `js/image-processing.js` after `stackImages`:

```js
/**
 * Stitch multiple images using 2D block matching with scale normalization.
 * images: array of { canvas, brightness } objects, ordered top-to-bottom.
 * mode: 'smart' (2D matching, default) or 'stack' (simple vertical stack).
 * createCanvasFn: optional factory for canvas creation (for testing).
 * Returns { canvas, warnings, pairResults }.
 */
export function stitchImages(images, mode = 'smart', createCanvasFn) {
  const _createCanvas = createCanvasFn || (() => document.createElement('canvas'));

  if (images.length === 0) return { canvas: null, warnings: ['No images provided'], pairResults: [] };
  if (images.length === 1) return { canvas: images[0].canvas, warnings: [], pairResults: [] };

  const warnings = [];

  // ── Scale normalization ──
  const scaleInfo = normalizeScales(images.map(img => img.canvas));

  // Create scaled canvases
  const scaled = images.map((img, i) => {
    const { width: newW, height: newH } = scaleInfo.scaledDimensions[i];
    const factor = scaleInfo.scaleFactors[i];

    if (factor === 1) return img.canvas;

    warnings.push(`Photo ${i + 1} scaled ${factor > 1 ? 'up' : 'down'} by ${Math.round(Math.abs(factor - 1) * 100)}% to match receipt width.`);

    const c = _createCanvas();
    c.width = newW;
    c.height = newH;
    const ctx = c.getContext('2d');
    ctx.drawImage(img.canvas, 0, 0, newW, newH);
    return c;
  });

  const width = scaleInfo.targetWidth;

  // ── Stack mode ──
  if (mode === 'stack') {
    const result = stackImages(scaled, _createCanvas);
    return { canvas: result.canvas, warnings, pairResults: [] };
  }

  // ── Smart stitch mode ──
  const pairResults = [];
  const offsets = [{ x: 0, y: 0 }]; // cumulative offsets for each image
  let fallbackPairs = [];

  for (let i = 1; i < scaled.length; i++) {
    const prevCanvas = scaled[i - 1];
    const currCanvas = scaled[i];

    // Get ImageData for 2D matching
    const prevCtx = prevCanvas.getContext('2d');
    const currCtx = currCanvas.getContext('2d');
    const prevData = prevCtx.getImageData(0, 0, prevCanvas.width, prevCanvas.height);
    const currData = currCtx.getImageData(0, 0, currCanvas.width, currCanvas.height);

    const result = findStitchOffset2D(prevData, currData);

    if (result !== null) {
      pairResults.push({ pair: [i, i + 1], ...result });
      warnings.push(`Photos ${i} and ${i + 1} matched with ${Math.round(result.confidence * 100)}% confidence.`);

      const prevOffset = offsets[i - 1];
      offsets.push({
        x: prevOffset.x + result.offsetX,
        y: prevOffset.y + prevCanvas.height - result.offsetY,
      });
    } else {
      pairResults.push({ pair: [i, i + 1], offsetX: 0, offsetY: 0, confidence: 0 });
      warnings.push(`Photos ${i} and ${i + 1} could not be matched — stacked instead.`);
      fallbackPairs.push(i);

      const prevOffset = offsets[i - 1];
      offsets.push({
        x: 0,
        y: prevOffset.y + prevCanvas.height + 2, // 2px separator
      });
    }
  }

  // ── Compute output dimensions ──
  // Find bounding box of all placed images
  let minX = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (let i = 0; i < scaled.length; i++) {
    const ox = offsets[i].x;
    minX = Math.min(minX, ox);
    maxX = Math.max(maxX, ox + scaled[i].width);
    maxY = Math.max(maxY, offsets[i].y + scaled[i].height);
  }

  const outW = maxX - minX;
  const outH = maxY;
  const shiftX = -minX; // shift all images so leftmost is at x=0

  // ── Composite ──
  const outCanvas = _createCanvas();
  outCanvas.width = outW;
  outCanvas.height = outH;
  const ctx = outCanvas.getContext('2d');

  for (let i = 0; i < scaled.length; i++) {
    const img = scaled[i];
    const ox = offsets[i].x + shiftX;
    const oy = offsets[i].y;

    if (i > 0 && !fallbackPairs.includes(i)) {
      // Cross-fade overlap region
      const prevOy = offsets[i - 1].y;
      const prevBottom = prevOy + scaled[i - 1].height;
      const overlapHeight = prevBottom - oy;

      if (overlapHeight > 0) {
        // Clear overlap region
        ctx.clearRect(ox, oy, img.width, overlapHeight);

        for (let row = 0; row < overlapHeight; row++) {
          const tB = (row + 1) / (overlapHeight + 1);
          const tA = 1 - tB;

          ctx.globalAlpha = tA;
          const prevOx = offsets[i - 1].x + shiftX;
          ctx.drawImage(scaled[i - 1],
            0, scaled[i - 1].height - overlapHeight + row, scaled[i - 1].width, 1,
            prevOx, oy + row, scaled[i - 1].width, 1);

          ctx.globalAlpha = tB;
          ctx.drawImage(img, 0, row, img.width, 1, ox, oy + row, img.width, 1);
        }

        ctx.globalAlpha = 1;
        const remainY = overlapHeight;
        const remainH = img.height - remainY;
        if (remainH > 0) {
          ctx.drawImage(img, 0, remainY, img.width, remainH, ox, oy + remainY, img.width, remainH);
        }
      } else {
        ctx.drawImage(img, 0, 0, img.width, img.height, ox, oy, img.width, img.height);
      }
    } else if (i > 0 && fallbackPairs.includes(i)) {
      // Stack with separator
      ctx.fillStyle = '#e2e8f0';
      ctx.fillRect(0, oy - 2, outW, 2);
      ctx.drawImage(img, 0, 0, img.width, img.height, ox, oy, img.width, img.height);
    } else {
      // First image
      ctx.drawImage(img, 0, 0, img.width, img.height, ox, oy, img.width, img.height);
    }
  }

  // ── Crop to clean rectangle (trim horizontal overhang) ──
  // The output already has the correct bounding box from our calculations

  return { canvas: outCanvas, warnings, pairResults };
}
```

- [ ] **Step 2: Run all tests**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/*.mjs`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add js/image-processing.js
git commit -m "feat: rewrite stitchImages with scale normalization and 2D matching"
```

---

### Task 5: UI — Stitch Mode Toggle and Updated Warnings

Add the stitch mode toggle to the session UI, pass mode through to stitching, and update warning display.

**Files:**
- Modify: `js/capture-session.js`
- Modify: `index.html`

- [ ] **Step 1: Add `stitchMode` to CaptureSession**

In `js/capture-session.js`, add to the constructor (after `this.onChange = null;`):

```js
    this.stitchMode = 'smart'; // 'smart' or 'stack'
```

And add to the `clear()` method (after `this.nextId = 1;`):

```js
    this.stitchMode = 'smart';
```

- [ ] **Step 2: Add stitch mode toggle HTML to `index.html`**

In the session section, add a stitch mode toggle before the "Done" button group. Find:

```html
      <div class="btn-group" style="margin-top: 10px;">
        <button class="btn btn-success" id="btn-done" disabled>Done - Stitch &amp; Convert</button>
```

Add before it:

```html
      <div class="stitch-mode-toggle" id="stitch-mode-toggle" style="margin-top: 12px;">
        <span class="stitch-mode-label">Stitch mode:</span>
        <button class="stitch-mode-btn active" id="btn-mode-smart" data-mode="smart">Smart Stitch</button>
        <button class="stitch-mode-btn" id="btn-mode-stack" data-mode="stack">Stack Only</button>
      </div>
```

- [ ] **Step 3: Add stitch mode toggle CSS**

Add to the `<style>` block before the closing `</style>`:

```css
    /* ─── Stitch mode toggle ─────────────────────────────────────── */
    .stitch-mode-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.85rem;
    }

    .stitch-mode-label {
      color: var(--text-muted);
      flex-shrink: 0;
    }

    .stitch-mode-btn {
      padding: 6px 14px;
      border: 1px solid var(--border);
      background: var(--surface);
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 500;
      cursor: pointer;
      color: var(--text-muted);
    }

    .stitch-mode-btn.active {
      background: var(--primary);
      color: #fff;
      border-color: var(--primary);
    }
```

- [ ] **Step 4: Wire up the toggle and update stitching call in the script block**

Add DOM refs and event handlers in the `<script type="module">` block. After the viewfinder section code, add:

```js
    // ─── Stitch Mode Toggle ──────────────────────────────────────────────────
    const btnModeSmart = document.getElementById('btn-mode-smart');
    const btnModeStack = document.getElementById('btn-mode-stack');

    btnModeSmart.addEventListener('click', () => {
      session.stitchMode = 'smart';
      btnModeSmart.classList.add('active');
      btnModeStack.classList.remove('active');
    });

    btnModeStack.addEventListener('click', () => {
      session.stitchMode = 'stack';
      btnModeStack.classList.add('active');
      btnModeSmart.classList.remove('active');
    });
```

Update the `btnDone` click handler to pass the mode. Find the line:

```js
        const stitchResult = stitchImages(session.getStitchInput());
```

Replace with:

```js
        const stitchResult = stitchImages(session.getStitchInput(), session.stitchMode);
```

- [ ] **Step 5: Verify syntax**

Run: `cd /home/drobinson911/receipt-cutter && node -c js/capture-session.js`
Expected: No syntax errors.

- [ ] **Step 6: Run all tests for regression**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/*.mjs`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add js/capture-session.js index.html
git commit -m "feat: add stitch mode toggle (smart/stack) to capture session UI"
```

---

### Task 6: Update Service Worker and Integration Testing

Update SW cache, manual testing, bug fixes.

**Files:**
- Modify: `sw.js`
- Potentially any file

- [ ] **Step 1: Bump SW cache version**

In `sw.js`, change `const CACHE_NAME = 'receipt-cutter-v2';` to `const CACHE_NAME = 'receipt-cutter-v3';`

- [ ] **Step 2: Run all unit tests**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/*.mjs`
Expected: All tests pass.

- [ ] **Step 3: Commit SW update**

```bash
git add sw.js
git commit -m "chore: bump SW cache version to v3"
```

- [ ] **Step 4: Manual integration testing**

Test in browser via `npx serve .`:

1. **Smart stitch flow**: Take 3 overlapping photos of a receipt at slightly different distances → verify scale normalization warning appears → verify 2D matching produces clean seams
2. **Stack mode flow**: Switch toggle to "Stack Only" → take 3 photos → verify they stack with separator lines, no overlap detection attempted
3. **Mixed fallback**: Take 3 photos where 2nd and 3rd don't overlap → verify 1+2 stitch and 3 stacks with warning
4. **Single photo**: Take 1 photo → Done → verify no stitching, straight to preview
5. **Cancel/reset**: Verify cancel and reset still work correctly

- [ ] **Step 5: Fix any issues found and commit**

```bash
git add -A
git commit -m "fix: address integration testing issues for improved stitching"
```
