import {
  PAGE_W, PAGE_H, MARGIN, GAP, USABLE_H,
  SEARCH_RANGE, BRIGHTNESS_THRESHOLD,
  getRowBrightness, findCutPoints, calcColumnsPerPage
} from './image-processing.js';

/**
 * Generates a multi-page PDF from a receipt image.
 * @param {HTMLImageElement} image - The loaded receipt image
 * @param {function} onProgress - Callback: (text, percent) => void
 * @returns {Promise<{blobUrl: string, numPages: number, numStrips: number, colsPerPage: number}>}
 */
export async function generatePdf(image, onProgress) {
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  onProgress('Loading image\u2026', 5);
  await sleep(50);

  // 1. Draw image to canvas
  const canvas = document.createElement('canvas');
  canvas.width  = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(image, 0, 0);

  onProgress('Analysing brightness\u2026', 15);
  await sleep(50);

  // 2. Row brightness
  const rowBrightness = getRowBrightness(canvas);

  onProgress('Finding cut points\u2026', 30);
  await sleep(50);

  // 3. Cut points
  const imgW = canvas.width;
  const imgH = canvas.height;
  const cutPoints = findCutPoints(rowBrightness, imgH, USABLE_H, SEARCH_RANGE, BRIGHTNESS_THRESHOLD);
  const numStrips = cutPoints.length - 1;

  // 4. Columns per page
  const colsPerPage = calcColumnsPerPage(imgW, PAGE_W, MARGIN, GAP);

  onProgress('Creating PDF\u2026', 45);
  await sleep(50);

  // 5. Create jsPDF instance
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({
    unit:   'px',
    format: [PAGE_W, PAGE_H],
    hotfixes: ['px_scaling'],
  });

  const numPages = Math.ceil(numStrips / colsPerPage);

  for (let p = 0; p < numPages; p++) {
    if (p > 0) doc.addPage([PAGE_W, PAGE_H]);

    const pageStrips = [];
    const stripStart = p * colsPerPage;
    const stripEnd   = Math.min(stripStart + colsPerPage, numStrips);

    // Extract strip canvases for this page
    for (let s = stripStart; s < stripEnd; s++) {
      const top    = cutPoints[s];
      const bottom = cutPoints[s + 1];
      const sh     = bottom - top;

      const stripCanvas = document.createElement('canvas');
      stripCanvas.width  = imgW;
      stripCanvas.height = sh;
      const sCtx = stripCanvas.getContext('2d');
      sCtx.drawImage(canvas, 0, top, imgW, sh, 0, 0, imgW, sh);
      pageStrips.push(stripCanvas);
    }

    // Center columns horizontally
    const numCols     = pageStrips.length;
    const totalColsW  = numCols * imgW + (numCols - 1) * GAP;
    const xStart      = Math.round((PAGE_W - totalColsW) / 2);

    for (let c = 0; c < numCols; c++) {
      const x          = xStart + c * (imgW + GAP);
      const y          = MARGIN;
      const stripCanvas = pageStrips[c];
      const imgData    = stripCanvas.toDataURL('image/jpeg', 0.92);
      doc.addImage(imgData, 'JPEG', x, y, imgW, stripCanvas.height);
      stripCanvas.width  = 0;
      stripCanvas.height = 0;
    }

    const pct = 45 + Math.round(((p + 1) / numPages) * 50);
    onProgress(`Rendering page ${p + 1} of ${numPages}\u2026`, pct);
    await sleep(30);
  }

  onProgress('Finalising\u2026', 97);
  await sleep(50);

  // 6. Create blob URL
  const pdfBlob = doc.output('blob');
  const blobUrl = URL.createObjectURL(pdfBlob);

  return { blobUrl, numPages, numStrips, colsPerPage };
}
