import { getRowBrightness, autoCrop } from './image-processing.js';

/**
 * Manages a multi-photo capture session with auto-cropping, reordering, and removal.
 */
export class CaptureSession {
  constructor() {
    this.photos = []; // Array of { id, originalImg, croppedCanvas, brightness, fileName }
    this.nextId = 1;
    this.onChange = null; // callback when photos array changes
  }

  /**
   * Load an image file, auto-crop it, compute brightness, and add to the session.
   * @param {File} file
   * @returns {Promise<void>}
   */
  async addPhoto(file) {
    const img = await this._loadImage(file);

    // Draw original to a full-res canvas
    const srcCanvas = document.createElement('canvas');
    srcCanvas.width = img.naturalWidth;
    srcCanvas.height = img.naturalHeight;
    const srcCtx = srcCanvas.getContext('2d');
    srcCtx.drawImage(img, 0, 0);

    // Downsample for analysis (~800px wide)
    const ANALYSIS_WIDTH = 800;
    const scale = Math.min(1, ANALYSIS_WIDTH / srcCanvas.width);
    const smallW = Math.round(srcCanvas.width * scale);
    const smallH = Math.round(srcCanvas.height * scale);

    const smallCanvas = document.createElement('canvas');
    smallCanvas.width = smallW;
    smallCanvas.height = smallH;
    const smallCtx = smallCanvas.getContext('2d');
    smallCtx.drawImage(srcCanvas, 0, 0, smallW, smallH);

    // Auto-crop on downsampled version
    const smallData = smallCtx.getImageData(0, 0, smallW, smallH);
    const cropRect = autoCrop(smallData);

    // Scale crop rectangle back to original resolution
    const invScale = 1 / scale;
    const origX = Math.round(cropRect.x * invScale);
    const origY = Math.round(cropRect.y * invScale);
    const origW = Math.round(cropRect.w * invScale);
    const origH = Math.round(cropRect.h * invScale);

    // Clamp to source bounds
    const clampedW = Math.min(origW, srcCanvas.width - origX);
    const clampedH = Math.min(origH, srcCanvas.height - origY);

    // Crop from the original full-res canvas
    const croppedCanvas = document.createElement('canvas');
    croppedCanvas.width = clampedW;
    croppedCanvas.height = clampedH;
    const croppedCtx = croppedCanvas.getContext('2d');
    croppedCtx.drawImage(srcCanvas, origX, origY, clampedW, clampedH, 0, 0, clampedW, clampedH);

    // Compute brightness on the cropped canvas
    const brightness = getRowBrightness(croppedCanvas);

    // Clean up temporary canvases
    smallCanvas.width = 0;
    smallCanvas.height = 0;

    const photo = {
      id: this.nextId++,
      originalImg: img,
      croppedCanvas,
      brightness,
      fileName: file.name,
    };

    this.photos.push(photo);

    // Clean up source canvas
    srcCanvas.width = 0;
    srcCanvas.height = 0;

    if (this.onChange) this.onChange();
  }

  /**
   * Add a photo from a canvas element (e.g., from camera viewfinder capture).
   * @param {HTMLCanvasElement} sourceCanvas - The captured frame
   * @param {string} [fileName] - Optional filename, defaults to timestamp
   * @returns {Promise<void>}
   */
  async addPhotoFromCanvas(sourceCanvas, fileName) {
    const name = fileName || `capture_${Date.now()}.jpg`;

    // Downsample for analysis (~800px wide)
    const ANALYSIS_WIDTH = 800;
    const scale = Math.min(1, ANALYSIS_WIDTH / sourceCanvas.width);
    const smallW = Math.round(sourceCanvas.width * scale);
    const smallH = Math.round(sourceCanvas.height * scale);

    const smallCanvas = document.createElement('canvas');
    smallCanvas.width = smallW;
    smallCanvas.height = smallH;
    const smallCtx = smallCanvas.getContext('2d');
    smallCtx.drawImage(sourceCanvas, 0, 0, smallW, smallH);

    // Auto-crop on downsampled version
    const smallData = smallCtx.getImageData(0, 0, smallW, smallH);
    const cropRect = autoCrop(smallData);

    // Scale crop rectangle back to original resolution
    const invScale = 1 / scale;
    const origX = Math.round(cropRect.x * invScale);
    const origY = Math.round(cropRect.y * invScale);
    const origW = Math.round(cropRect.w * invScale);
    const origH = Math.round(cropRect.h * invScale);

    // Clamp to source bounds
    const clampedW = Math.min(origW, sourceCanvas.width - origX);
    const clampedH = Math.min(origH, sourceCanvas.height - origY);

    // Crop from the original full-res canvas
    const croppedCanvas = document.createElement('canvas');
    croppedCanvas.width = clampedW;
    croppedCanvas.height = clampedH;
    const croppedCtx = croppedCanvas.getContext('2d');
    croppedCtx.drawImage(sourceCanvas, origX, origY, clampedW, clampedH, 0, 0, clampedW, clampedH);

    // Compute brightness on the cropped canvas
    const brightness = getRowBrightness(croppedCanvas);

    // Clean up
    smallCanvas.width = 0;
    smallCanvas.height = 0;

    // Create a placeholder image for originalImg
    const originalImg = new Image();
    originalImg.src = sourceCanvas.toDataURL('image/jpeg', 0.92);
    await new Promise(resolve => { originalImg.onload = resolve; });

    const photo = {
      id: this.nextId++,
      originalImg,
      croppedCanvas,
      brightness,
      fileName: name,
    };

    this.photos.push(photo);

    if (this.onChange) this.onChange();
  }

  /**
   * Remove a photo by its id.
   * @param {number} id
   */
  removePhoto(id) {
    const idx = this.photos.findIndex(p => p.id === id);
    if (idx !== -1) {
      this.photos.splice(idx, 1);
      if (this.onChange) this.onChange();
    }
  }

  /**
   * Reorder: move photo from one index to another.
   * @param {number} fromIndex
   * @param {number} toIndex
   */
  reorder(fromIndex, toIndex) {
    if (fromIndex < 0 || fromIndex >= this.photos.length) return;
    if (toIndex < 0 || toIndex >= this.photos.length) return;
    const [item] = this.photos.splice(fromIndex, 1);
    this.photos.splice(toIndex, 0, item);
    if (this.onChange) this.onChange();
  }

  /**
   * Replace the cropped canvas with the original image (no auto-crop) for a given photo.
   * @param {number} id
   */
  useOriginal(id) {
    const photo = this.photos.find(p => p.id === id);
    if (!photo) return;

    const img = photo.originalImg;
    const canvas = document.createElement('canvas');
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);

    photo.croppedCanvas = canvas;
    photo.brightness = getRowBrightness(canvas);

    if (this.onChange) this.onChange();
  }

  /**
   * Clear the session, resetting all state.
   */
  clear() {
    this.photos = [];
    this.nextId = 1;
    if (this.onChange) this.onChange();
  }

  /**
   * Returns data formatted for stitchImages().
   * @returns {Array<{canvas: HTMLCanvasElement, brightness: Float32Array}>}
   */
  getStitchInput() {
    return this.photos.map(p => ({
      canvas: p.croppedCanvas,
      brightness: p.brightness,
    }));
  }

  /**
   * Load a File as an HTMLImageElement.
   * @param {File} file
   * @returns {Promise<HTMLImageElement>}
   * @private
   */
  _loadImage(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = e => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error(`Failed to load image: ${file.name}`));
        img.src = e.target.result;
      };
      reader.onerror = () => reject(new Error(`Failed to read file: ${file.name}`));
      reader.readAsDataURL(file);
    });
  }
}
