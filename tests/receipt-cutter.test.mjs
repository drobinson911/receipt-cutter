/**
 * Unit tests for Receipt Cutter core processing functions.
 * Functions are imported from the js/ modules.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  findCutPoints,
  calcColumnsPerPage,
  DPI,
  PAGE_W,
  PAGE_H,
  MARGIN,
  GAP,
  USABLE_H,
  SEARCH_RANGE,
  BRIGHTNESS_THRESHOLD,
} from '../js/image-processing.js';

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Build a Float32Array of uniform brightness. */
function uniformBrightness(height, value) {
  const arr = new Float32Array(height);
  arr.fill(value);
  return arr;
}

/** Build a Float32Array mostly dark, with bright rows at the given indices. */
function brightnessWithGaps(height, brightRows, darkValue = 10, brightValue = 245) {
  const arr = new Float32Array(height);
  arr.fill(darkValue);
  for (const r of brightRows) {
    arr[r] = brightValue;
  }
  return arr;
}

// ─── findCutPoints tests ──────────────────────────────────────────────────────

test('findCutPoints: single strip when image fits in one page', () => {
  // Image height <= USABLE_H → no interior cuts needed
  const imgHeight = USABLE_H - 100; // 2990, definitely fits
  const brightness = uniformBrightness(imgHeight, 10); // all dark — no gaps
  const cuts = findCutPoints(brightness, imgHeight, USABLE_H, SEARCH_RANGE, BRIGHTNESS_THRESHOLD);

  // Expect exactly [0, imgHeight] — one strip, no interior cut
  assert.deepEqual(cuts, [0, imgHeight]);
});

test('findCutPoints: cuts at whitespace gaps when available', () => {
  // Image that needs 2 strips; put a bright gap exactly at the ideal cut point
  const imgHeight = USABLE_H * 2 + 100; // needs 3 strips
  const targetH   = USABLE_H;

  // Place bright gaps exactly at the first and second ideal cut positions
  const gap1 = targetH;
  const gap2 = targetH * 2;
  const brightness = brightnessWithGaps(imgHeight, [gap1, gap2]);

  const cuts = findCutPoints(brightness, imgHeight, targetH, SEARCH_RANGE, BRIGHTNESS_THRESHOLD);

  // Should be [0, gap1, gap2, imgHeight]
  assert.equal(cuts[0], 0);
  assert.equal(cuts[1], gap1);
  assert.equal(cuts[2], gap2);
  assert.equal(cuts[cuts.length - 1], imgHeight);
});

test('findCutPoints: falls back to ideal cut when no gap exists', () => {
  // All rows are dark — no whitespace anywhere
  const imgHeight = USABLE_H + 500; // needs 2 strips
  const brightness = uniformBrightness(imgHeight, 5); // uniformly dark
  const cuts = findCutPoints(brightness, imgHeight, USABLE_H, SEARCH_RANGE, BRIGHTNESS_THRESHOLD);

  // Interior cut should be exactly at ideal position
  assert.equal(cuts[0], 0);
  assert.equal(cuts[1], USABLE_H);          // fallback to ideal
  assert.equal(cuts[cuts.length - 1], imgHeight);
});

test('findCutPoints: prefers gap closest to ideal cut', () => {
  // Two candidate bright rows: one 50px before ideal, one 100px after ideal.
  // The closer one (50px before) should win.
  const imgHeight  = USABLE_H + 500;
  const idealCut   = USABLE_H;
  const closerGap  = idealCut - 50;  // distance 50 — should be chosen
  const fartherGap = idealCut + 100; // distance 100

  const brightness = brightnessWithGaps(imgHeight, [closerGap, fartherGap]);
  const cuts = findCutPoints(brightness, imgHeight, USABLE_H, SEARCH_RANGE, BRIGHTNESS_THRESHOLD);

  assert.equal(cuts[1], closerGap);
});

// ─── calcColumnsPerPage tests ─────────────────────────────────────────────────

test('calcColumnsPerPage: 2 columns for 935px-wide receipt', () => {
  // A typical narrow thermal receipt at 300 DPI (~3.1 inches wide)
  const stripWidth = 935;
  const cols = calcColumnsPerPage(stripWidth, PAGE_W, MARGIN, GAP);
  assert.equal(cols, 2);
});

test('calcColumnsPerPage: 1 column for very wide receipt (2000px)', () => {
  const stripWidth = 2000;
  const cols = calcColumnsPerPage(stripWidth, PAGE_W, MARGIN, GAP);
  assert.equal(cols, 1);
});

test('calcColumnsPerPage: 4+ columns for narrow receipt (500px)', () => {
  const stripWidth = 500;
  const cols = calcColumnsPerPage(stripWidth, PAGE_W, MARGIN, GAP);
  assert.ok(cols >= 4, `Expected >= 4 columns, got ${cols}`);
});
