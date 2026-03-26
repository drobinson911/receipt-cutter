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

/**
 * Compute 2D normalized cross-correlation between a template patch and a
 * region of a search image. Both use { data, width, height } ImageData format.
 * Template is placed at (tx, ty) within the search image's coordinate space.
 * Uses grayscale brightness: (R+G+B)/3.
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
 * Compute mean absolute error between a template and a region of the search image.
 * Returns average per-pixel absolute brightness difference.
 */
function computeMAE(templateData, tW, tH, searchData, sW, sH, tx, ty) {
  let sumErr = 0, count = 0;
  for (let y = 0; y < tH; y++) {
    for (let x = 0; x < tW; x++) {
      const sx = tx + x;
      const sy = ty + y;
      if (sx < 0 || sx >= sW || sy < 0 || sy >= sH) continue;
      const ti = (y * tW + x) * 4;
      const si = (sy * sW + sx) * 4;
      const tVal = (templateData[ti] + templateData[ti + 1] + templateData[ti + 2]) / 3;
      const sVal = (searchData[si] + searchData[si + 1] + searchData[si + 2]) / 3;
      sumErr += Math.abs(tVal - sVal);
      count++;
    }
  }
  if (count === 0) return 255;
  return sumErr / count;
}

/**
 * Find the 2D overlap offset between two images using template matching.
 * imgA, imgB: { data, width, height } ImageData-like objects.
 * Extracts a horizontal strip from the bottom of A and searches the top of B.
 * Uses coarse-to-fine: 2x downsample for coarse pass, full-res refinement.
 * After finding the horizontal offset, scans overlap depths to find the true
 * overlap using full-depth MAE validation.
 * Returns { offsetX, offsetY, confidence } or null if no good match.
 * offsetX: horizontal shift of B relative to A (positive = B shifted right)
 * offsetY: number of rows from top of B that overlap with bottom of A
 */
export function findStitchOffset2D(imgA, imgB) {
  const TEMPLATE_HEIGHT = 60;
  const SEARCH_FRAC = 0.4;
  const MAX_SHIFT_X = Math.round(imgA.width * 0.15);
  const NCC_THRESHOLD = 0.6;
  const MAE_THRESHOLD = 15;

  // Extract template: bottom strip of A
  const tY = imgA.height - Math.min(TEMPLATE_HEIGHT, Math.round(imgA.height * 0.15));
  const tH = imgA.height - tY;
  const tW = imgA.width;
  const templateData = new Uint8ClampedArray(tW * tH * 4);
  for (let y = 0; y < tH; y++) {
    const srcOffset = ((tY + y) * imgA.width) * 4;
    const dstOffset = (y * tW) * 4;
    templateData.set(imgA.data.subarray(srcOffset, srcOffset + tW * 4), dstOffset);
  }

  // Search region: top portion of B
  const searchH = Math.min(Math.round(imgB.height * SEARCH_FRAC), imgB.height);

  // Coarse pass: downsample 2x
  const cScale = 0.5;
  const cTW = Math.round(tW * cScale);
  const cTH = Math.round(tH * cScale);
  const cSW = Math.round(imgB.width * cScale);
  const cSH = Math.round(searchH * cScale);
  const cMaxShiftX = Math.round(MAX_SHIFT_X * cScale / 2) * 2; // ensure even for step alignment
  const cFullH = Math.round(imgB.height * cScale);

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
  const cSearch = downsample(imgB.data, imgB.width, imgB.height, cSW, cFullH);

  const candidates = [];
  const stepX = 2;
  const stepY = 2;

  for (let cy = 0; cy <= cSH - cTH; cy += stepY) {
    for (let cx = -cMaxShiftX; cx <= cMaxShiftX; cx += stepX) {
      const ncc = computeNCC(cTemplate, cTW, cTH, cSearch, cSW, cFullH, cx, cy);
      if (ncc > 0.3) {
        candidates.push({ x: cx, y: cy, score: ncc });
      }
    }
  }

  if (candidates.length === 0) return null;

  candidates.sort((a, b) => b.score - a.score);
  const topCandidates = candidates.slice(0, 20);

  // Fine pass: search around each candidate at full resolution
  // Collect all good template matches
  const fineMatches = [];

  for (const c of topCandidates) {
    const fullX = Math.round(c.x / cScale);
    const fullY = Math.round(c.y / cScale);

    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const fx = fullX + dx;
        const fy = fullY + dy;
        if (fy < 0 || fy + tH > imgB.height) continue;

        const ncc = computeNCC(templateData, tW, tH, imgB.data, imgB.width, imgB.height, fx, fy);
        const mae = computeMAE(templateData, tW, tH, imgB.data, imgB.width, imgB.height, fx, fy);
        if (mae <= MAE_THRESHOLD && ncc >= NCC_THRESHOLD) {
          fineMatches.push({ offsetX: fx, fy, ncc, mae });
        }
      }
    }
  }

  if (fineMatches.length === 0) return null;

  // Deduplicate: keep best NCC for each unique (offsetX, fy)
  const matchMap = new Map();
  for (const m of fineMatches) {
    const key = `${m.offsetX},${m.fy}`;
    if (!matchMap.has(key) || m.ncc > matchMap.get(key).ncc) {
      matchMap.set(key, m);
    }
  }
  const uniqueMatches = [...matchMap.values()];

  // For each unique offsetX, find the best overlap depth by scanning.
  // The template found at (offsetX, fy) implies the overlap starts at fy in B
  // and the template covers rows fy..fy+tH-1. The full overlap = fy + tH rows.
  // Validate by computing full-depth MAE: A's bottom (fy+tH) rows vs B's top (fy+tH) rows.
  let bestResult = null;

  // Collect unique offsetX values
  const offsetXs = [...new Set(uniqueMatches.map(m => m.offsetX))];

  for (const ox of offsetXs) {
    // Scan overlap depths from tH to searchH
    const maxDepth = Math.min(searchH, imgA.height);
    let bestDepthMAE = Infinity;
    let bestDepth = -1;

    for (let depth = tH; depth <= maxDepth; depth += 2) {
      // Compute MAE: A's bottom `depth` rows vs B's top `depth` rows at offsetX=ox
      let sumErr = 0, count = 0;
      for (let dy = 0; dy < depth; dy++) {
        const aRow = imgA.height - depth + dy;
        const bRow = dy;
        if (aRow < 0 || bRow >= imgB.height) break;
        for (let x = 0; x < tW; x++) {
          const bx = ox + x;
          if (bx < 0 || bx >= imgB.width) continue;
          const ai = (aRow * imgA.width + x) * 4;
          const bi = (bRow * imgB.width + bx) * 4;
          const aVal = (imgA.data[ai] + imgA.data[ai + 1] + imgA.data[ai + 2]) / 3;
          const bVal = (imgB.data[bi] + imgB.data[bi + 1] + imgB.data[bi + 2]) / 3;
          sumErr += Math.abs(aVal - bVal);
          count++;
        }
      }
      if (count === 0) continue;
      const depthMAE = sumErr / count;
      if (depthMAE < bestDepthMAE) {
        bestDepthMAE = depthMAE;
        bestDepth = depth;
      }
    }

    if (bestDepthMAE > MAE_THRESHOLD || bestDepth < 0) continue;

    // Validate: the depth must differ from tH (reject matches that only work at template size)
    // Also compute NCC at the best depth for confidence
    const ncc = computeNCC(
      // Use full-depth template
      (() => {
        const fullT = new Uint8ClampedArray(tW * bestDepth * 4);
        for (let y = 0; y < bestDepth; y++) {
          const srcOffset = ((imgA.height - bestDepth + y) * imgA.width) * 4;
          fullT.set(imgA.data.subarray(srcOffset, srcOffset + tW * 4), y * tW * 4);
        }
        return fullT;
      })(),
      tW, bestDepth, imgB.data, imgB.width, imgB.height, ox, 0
    );

    if (ncc < NCC_THRESHOLD) continue;

    if (bestResult === null || bestDepthMAE < bestResult.bestMAE ||
        (bestDepthMAE <= bestResult.bestMAE + 0.5 && ncc > bestResult.confidence)) {
      bestResult = {
        offsetX: ox,
        offsetY: bestDepth,
        confidence: ncc,
        bestMAE: bestDepthMAE,
      };
    }
  }

  if (bestResult === null) return null;

  // Uniqueness check: reject if too many alternative offsetX values also produce
  // good depth matches, which indicates a periodic/synthetic pattern rather than
  // genuine image overlap.
  const checkThreshold = bestResult.bestMAE + 8;
  let altMatchCount = 0;
  const altStep = 5;
  const altRange = MAX_SHIFT_X;
  const maxDepthCheck = Math.min(searchH, imgA.height);

  for (let altOx = -altRange; altOx <= altRange; altOx += altStep) {
    if (Math.abs(altOx - bestResult.offsetX) < altStep) continue; // skip near best

    for (let depth = tH; depth <= maxDepthCheck; depth += 4) {
      let sumErr = 0, count = 0;
      for (let dy = 0; dy < depth; dy++) {
        const aRow = imgA.height - depth + dy;
        if (aRow < 0) continue;
        const bRow = dy;
        if (bRow >= imgB.height) break;
        for (let x = 0; x < tW; x++) {
          const bx = altOx + x;
          if (bx < 0 || bx >= imgB.width) continue;
          const ai = (aRow * imgA.width + x) * 4;
          const bi = (bRow * imgB.width + bx) * 4;
          const aVal = (imgA.data[ai] + imgA.data[ai + 1] + imgA.data[ai + 2]) / 3;
          const bVal = (imgB.data[bi] + imgB.data[bi + 1] + imgB.data[bi + 2]) / 3;
          sumErr += Math.abs(aVal - bVal);
          count++;
        }
      }
      if (count > 0 && sumErr / count < checkThreshold) {
        altMatchCount++;
        break; // found a match at this ox, move to next
      }
    }
  }

  // If more than 3 alternative offsetX values have good matches, it's likely spurious
  if (altMatchCount > 3) return null;

  // Return without internal fields
  return {
    offsetX: bestResult.offsetX,
    offsetY: bestResult.offsetY,
    confidence: bestResult.confidence,
  };
}

/**
 * Stack images vertically with separator lines between them.
 * images: array of { data, width, height } or canvas-like objects.
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
      ctx.fillStyle = '#e2e8f0';
      ctx.fillRect(0, y, width, SEPARATOR_H);
      y += SEPARATOR_H;
    }
    ctx.drawImage(images[i], 0, 0, images[i].width, images[i].height, 0, y, width, images[i].height);
    y += images[i].height;
  }

  return { canvas: out };
}
