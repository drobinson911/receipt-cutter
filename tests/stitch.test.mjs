import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findStitchOffset } from '../js/image-processing.js';

test('findStitchOffset: detects exact overlap with matching patterns', () => {
  const aHeight = 1000;
  const bHeight = 1000;
  const overlap = 200;

  const aBrightness = new Float32Array(aHeight);
  const bBrightness = new Float32Array(bHeight);

  for (let i = 0; i < aHeight; i++) aBrightness[i] = (i * 7 + 13) % 256;
  for (let i = 0; i < overlap; i++) bBrightness[i] = aBrightness[aHeight - overlap + i];
  for (let i = overlap; i < bHeight; i++) bBrightness[i] = (i * 11 + 37) % 256;

  const result = findStitchOffset(aBrightness, bBrightness, 0.1, 0.5);

  assert.ok(result !== null, 'Should find a match');
  assert.equal(result.offset, overlap, `Expected offset ${overlap}, got ${result.offset}`);
  assert.ok(result.confidence > 0.7, `Confidence ${result.confidence} should be > 0.7`);
});

test('findStitchOffset: returns null when images do not overlap', () => {
  const aBrightness = new Float32Array(500);
  const bBrightness = new Float32Array(500);
  for (let i = 0; i < 500; i++) {
    aBrightness[i] = 50;
    bBrightness[i] = 200;
  }

  const result = findStitchOffset(aBrightness, bBrightness, 0.1, 0.5);

  if (result !== null) {
    assert.ok(result.confidence < 0.7, `Confidence should be low for non-overlapping images`);
  }
});

test('findStitchOffset: finds offset with noisy overlap', () => {
  const aHeight = 800;
  const bHeight = 800;
  const overlap = 150;

  const aBrightness = new Float32Array(aHeight);
  const bBrightness = new Float32Array(bHeight);

  for (let i = 0; i < aHeight; i++) aBrightness[i] = (i * 7 + 13) % 256;
  for (let i = 0; i < overlap; i++) {
    const noise = (Math.sin(i * 17) * 5);
    bBrightness[i] = Math.max(0, Math.min(255, aBrightness[aHeight - overlap + i] + noise));
  }
  for (let i = overlap; i < bHeight; i++) bBrightness[i] = (i * 11 + 37) % 256;

  const result = findStitchOffset(aBrightness, bBrightness, 0.1, 0.5);

  assert.ok(result !== null, 'Should find a match despite noise');
  assert.ok(Math.abs(result.offset - overlap) <= 2, `Offset ${result.offset} should be within 2 of ${overlap}`);
});
