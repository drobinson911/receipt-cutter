import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeScales, findStitchOffset2D, stackImages } from '../js/image-processing.js';

test('normalizeScales: returns target width as median of input widths', () => {
  const result = normalizeScales([
    { width: 600, height: 800 },
    { width: 800, height: 1000 },
    { width: 700, height: 900 },
  ]);
  assert.equal(result.targetWidth, 700);
});

test('normalizeScales: computes correct scale factors', () => {
  const result = normalizeScales([
    { width: 600, height: 800 },
    { width: 800, height: 1000 },
    { width: 700, height: 900 },
  ]);
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

/**
 * Create a synthetic grayscale image as { data, width, height }.
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
 * Create two images where B's top overlapH rows copy A's bottom overlapH rows,
 * optionally shifted by shiftX pixels.
 */
function makeOverlappingPair(width, heightA, heightB, overlapH, shiftX = 0) {
  const imgA = makeSyntheticImage(width, heightA, 1);
  const imgB = makeSyntheticImage(width, heightB, 2);

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

// ─── stackImages tests ──────────────────────────────────────────────────

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

test('stackImages: returns null for empty input', () => {
  const result = stackImages([], createMockCanvas);
  assert.equal(result.canvas, null);
});

test('stackImages: single image dimensions preserved', () => {
  const img = makeSyntheticImage(100, 200);
  const result = stackImages([img], createMockCanvas);
  assert.equal(result.canvas.width, 100);
  assert.equal(result.canvas.height, 200);
});

test('stackImages: two images stacked with separator', () => {
  const img1 = makeSyntheticImage(100, 200);
  const img2 = makeSyntheticImage(100, 300);
  const result = stackImages([img1, img2], createMockCanvas);
  assert.equal(result.canvas.width, 100);
  assert.equal(result.canvas.height, 502); // 200 + 2 + 300
});

test('stackImages: three images stacked with separators', () => {
  const img1 = makeSyntheticImage(100, 100);
  const img2 = makeSyntheticImage(100, 150);
  const img3 = makeSyntheticImage(100, 200);
  const result = stackImages([img1, img2, img3], createMockCanvas);
  assert.equal(result.canvas.width, 100);
  assert.equal(result.canvas.height, 454); // 100 + 2 + 150 + 2 + 200
});
