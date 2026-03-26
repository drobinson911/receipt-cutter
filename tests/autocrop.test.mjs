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
  const imageData = makeImageData(400, 600, 50, 80, 300, 440);
  const rect = autoCrop(imageData, 200);
  assert.ok(rect.x <= 50, `x=${rect.x} should be <= 50`);
  assert.ok(rect.y <= 80, `y=${rect.y} should be <= 80`);
  assert.ok(rect.x + rect.w >= 350, `right edge should be >= 350`);
  assert.ok(rect.y + rect.h >= 520, `bottom edge should be >= 520`);
});

test('autoCrop: returns full image when entire image is bright', () => {
  const imageData = makeImageData(400, 600, 0, 0, 400, 600, 250, 250);
  const rect = autoCrop(imageData, 200);
  assert.equal(rect.x, 0);
  assert.equal(rect.y, 0);
  assert.equal(rect.w, 400);
  assert.equal(rect.h, 600);
});

test('autoCrop: returns full image when entire image is dark', () => {
  const imageData = makeImageData(400, 600, 0, 0, 0, 0, 40, 40);
  const rect = autoCrop(imageData, 200);
  assert.equal(rect.x, 0);
  assert.equal(rect.y, 0);
  assert.equal(rect.w, 400);
  assert.equal(rect.h, 600);
});

test('autoCrop: receipt at edge of image crops correctly', () => {
  const imageData = makeImageData(400, 600, 0, 0, 200, 400);
  const rect = autoCrop(imageData, 200);
  assert.equal(rect.x, 0);
  assert.equal(rect.y, 0);
  assert.ok(rect.w >= 200 && rect.w <= 210, `w=${rect.w}`);
  assert.ok(rect.h >= 400 && rect.h <= 410, `h=${rect.h}`);
});
