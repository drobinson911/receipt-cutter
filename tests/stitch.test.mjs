import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeScales } from '../js/image-processing.js';

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
