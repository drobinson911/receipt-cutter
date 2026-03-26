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

  let top = 0;
  for (let y = 0; y < height; y++) {
    if (rowBrightFraction(y) >= RECEIPT_FRAC) { top = y; break; }
  }

  let bottom = height - 1;
  for (let y = height - 1; y >= 0; y--) {
    if (rowBrightFraction(y) >= RECEIPT_FRAC) { bottom = y; break; }
  }

  let left = 0;
  for (let x = 0; x < width; x++) {
    if (colBrightFraction(x) >= RECEIPT_FRAC) { left = x; break; }
  }

  let right = width - 1;
  for (let x = width - 1; x >= 0; x--) {
    if (colBrightFraction(x) >= RECEIPT_FRAC) { right = x; break; }
  }

  if (top >= bottom || left >= right) {
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
    const aStart = aLen - overlap;

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
    if (denom < 1e-6) continue;

    const ncc = num / denom;

    if (ncc >= bestScore) {
      bestScore = ncc;
      bestOffset = overlap;
    }
  }

  const CONFIDENCE_THRESHOLD = 0.7;
  if (bestScore < CONFIDENCE_THRESHOLD) {
    return null;
  }

  return { offset: bestOffset, confidence: bestScore };
}

/**
 * Stitch multiple images vertically using brightness-correlation overlap detection.
 * images: array of { canvas, brightness } objects, ordered top-to-bottom.
 * Returns { canvas, warnings } where:
 *   - canvas: the stitched result as a canvas element (or null if no images)
 *   - warnings: array of strings for any images where overlap detection failed
 */
export function stitchImages(images) {
  if (images.length === 0) return { canvas: null, warnings: ['No images provided'] };
  if (images.length === 1) return { canvas: images[0].canvas, warnings: [] };

  const warnings = [];
  const offsets = [0];
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
      const prevBottom = offsets[i - 1] + images[i - 1].canvas.height;
      const overlapHeight = prevBottom - y;

      if (overlapHeight > 0) {
        for (let row = 0; row < overlapHeight; row++) {
          const alpha = row / overlapHeight;
          ctx.globalAlpha = alpha;
          ctx.drawImage(img, 0, row, width, 1, 0, y + row, width, 1);
        }
        ctx.globalAlpha = 1;
        const remainY = overlapHeight;
        const remainH = img.height - remainY;
        if (remainH > 0) {
          ctx.drawImage(img, 0, remainY, width, remainH, 0, y + remainY, width, remainH);
        }
      } else {
        ctx.drawImage(img, 0, 0, width, img.height, 0, y, width, img.height);
      }
    } else {
      ctx.drawImage(img, 0, 0, width, img.height, 0, y, width, img.height);
    }
  }

  return { canvas: outCanvas, warnings };
}
