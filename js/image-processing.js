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
