// ─── Constants ───────────────────────────────────────────────────────────
export const DPI = 300;
export const PAGE_W_IN = 8.5;
export const PAGE_H_IN = 11.0;
export const MARGIN_IN = 0.35;
export const GAP_IN = 0.15;
export const SEARCH_RANGE_IN = 0.75;
export const BRIGHTNESS_THRESHOLD = 240;

export const PAGE_W      = Math.round(PAGE_W_IN      * DPI);  // 2550
export const PAGE_H      = Math.round(PAGE_H_IN      * DPI);  // 3300
export const MARGIN      = Math.round(MARGIN_IN      * DPI);  // 105
export const GAP         = Math.round(GAP_IN         * DPI);  //  45
export const USABLE_H    = PAGE_H - 2 * MARGIN;               // 3090
export const SEARCH_RANGE = Math.round(SEARCH_RANGE_IN * DPI); // 225

// ─── Core Processing Functions ───────────────────────────────────────────

/**
 * Returns a Float32Array of average brightness per row.
 * Each pixel's brightness = (R + G + B) / 3; row brightness = mean across all pixels.
 */
export function getRowBrightness(canvas) {
  const ctx = canvas.getContext('2d');
  const { width, height } = canvas;
  const imageData = ctx.getImageData(0, 0, width, height);
  const data = imageData.data; // RGBA flat array
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
 * For each ideal cut at targetHeight intervals, searches +/-searchRange for
 * the nearest row where brightness > brightnessThreshold.
 * Falls back to ideal cut if no bright row is found.
 * Returns array starting with 0, ending with imgHeight.
 */
export function findCutPoints(rowBrightness, imgHeight, targetHeight, searchRange, brightnessThreshold) {
  const cuts = [0];
  let pos = 0;

  while (pos + targetHeight < imgHeight) {
    const idealCut = pos + targetHeight;
    const searchStart = Math.max(0, idealCut - searchRange);
    const searchEnd   = Math.min(imgHeight, idealCut + searchRange);

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
 * Increments cols while: 2*margin + cols*stripWidth + (cols-1)*gap <= pageWidth
 */
export function calcColumnsPerPage(stripWidth, pageWidth, margin, gap) {
  let cols = 1;
  while (2 * margin + (cols + 1) * stripWidth + cols * gap <= pageWidth) {
    cols++;
  }
  return cols;
}

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

  function pixelBrightness(x, y) {
    const i = (y * width + x) * 4;
    return (data[i] + data[i + 1] + data[i + 2]) / 3;
  }

  function rowBrightFraction(y) {
    let count = 0;
    for (let x = 0; x < width; x++) {
      if (pixelBrightness(x, y) > threshold) count++;
    }
    return count / width;
  }

  function colBrightFraction(x) {
    let count = 0;
    for (let y = 0; y < height; y++) {
      if (pixelBrightness(x, y) > threshold) count++;
    }
    return count / height;
  }

  const RECEIPT_FRAC = 0.20;

  let top = -1;
  for (let y = 0; y < height; y++) {
    if (rowBrightFraction(y) >= RECEIPT_FRAC) { top = y; break; }
  }

  let bottom = -1;
  for (let y = height - 1; y >= 0; y--) {
    if (rowBrightFraction(y) >= RECEIPT_FRAC) { bottom = y; break; }
  }

  let left = -1;
  for (let x = 0; x < width; x++) {
    if (colBrightFraction(x) >= RECEIPT_FRAC) { left = x; break; }
  }

  let right = -1;
  for (let x = width - 1; x >= 0; x--) {
    if (colBrightFraction(x) >= RECEIPT_FRAC) { right = x; break; }
  }

  // If no bright region found at all, return full image
  if (top === -1 || bottom === -1 || left === -1 || right === -1 || top >= bottom || left >= right) {
    return { x: 0, y: 0, w: width, h: height };
  }

  const x = Math.max(0, left - MARGIN_PX);
  const y = Math.max(0, top - MARGIN_PX);
  const w = Math.min(width, right + MARGIN_PX + 1) - x;
  const h = Math.min(height, bottom + MARGIN_PX + 1) - y;

  return { x, y, w, h };
}

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
