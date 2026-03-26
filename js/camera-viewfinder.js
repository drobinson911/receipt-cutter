// js/camera-viewfinder.js

import { autoCrop } from './image-processing.js';

/**
 * Custom camera viewfinder with real-time crop detection and ghost overlay.
 */
export class CameraViewfinder {
  /**
   * @param {Object} options
   * @param {HTMLVideoElement} options.video - Video element for camera feed
   * @param {HTMLCanvasElement} options.overlayCanvas - Canvas layered on top for overlays
   * @param {Function} options.onCapture - Called with (canvas) when user captures a frame
   * @param {Function} options.getLastPhoto - Returns the last photo's croppedCanvas or null
   */
  constructor({ video, overlayCanvas, onCapture, getLastPhoto }) {
    this.video = video;
    this.overlay = overlayCanvas;
    this.onCapture = onCapture;
    this.getLastPhoto = getLastPhoto;

    this.stream = null;
    this.track = null;
    this.animFrameId = null;
    this.lastFrameTime = 0;
    this.ghostVisible = true;
    this.flashSupported = false;
    this.flashOn = false;

    // Smoothed crop rect (for lerp)
    this.smoothRect = null;

    // Analysis canvas (reused across frames)
    this.analysisCanvas = document.createElement('canvas');
  }

  /**
   * Open the camera and start the detection loop.
   */
  async open() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: 'environment',
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    });

    this.video.srcObject = this.stream;
    await this.video.play();

    this.track = this.stream.getVideoTracks()[0];

    // Check flash/torch support
    try {
      const capabilities = this.track.getCapabilities();
      this.flashSupported = capabilities.torch === true;
    } catch {
      this.flashSupported = false;
    }

    this._startDetectionLoop();
  }

  /**
   * Stop the camera and detection loop.
   */
  close() {
    this._stopDetectionLoop();

    if (this.stream) {
      this.stream.getTracks().forEach(t => t.stop());
      this.stream = null;
      this.track = null;
    }

    this.video.srcObject = null;
    this.smoothRect = null;
    this.flashOn = false;

    const ctx = this.overlay.getContext('2d');
    ctx.clearRect(0, 0, this.overlay.width, this.overlay.height);
  }

  /**
   * Capture the current video frame as a full-resolution canvas.
   */
  captureFrame() {
    const canvas = document.createElement('canvas');
    canvas.width = this.video.videoWidth;
    canvas.height = this.video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(this.video, 0, 0);

    if (this.onCapture) {
      this.onCapture(canvas);
    }

    return canvas;
  }

  /**
   * Toggle the flash/torch.
   */
  async toggleFlash() {
    if (!this.flashSupported || !this.track) return false;

    this.flashOn = !this.flashOn;
    try {
      await this.track.applyConstraints({
        advanced: [{ torch: this.flashOn }],
      });
    } catch {
      this.flashOn = false;
    }
    return this.flashOn;
  }

  /**
   * Toggle ghost overlay visibility.
   */
  toggleGhost() {
    this.ghostVisible = !this.ghostVisible;
    return this.ghostVisible;
  }

  // ─── Private ─────────────────────────────────────────────────────────────

  _startDetectionLoop() {
    const FRAME_INTERVAL = 66; // ~15fps
    const ANALYSIS_WIDTH = 200;
    const LERP_FACTOR = 0.3;

    const loop = (timestamp) => {
      this.animFrameId = requestAnimationFrame(loop);

      if (timestamp - this.lastFrameTime < FRAME_INTERVAL) return;
      this.lastFrameTime = timestamp;

      const vw = this.video.videoWidth;
      const vh = this.video.videoHeight;
      if (vw === 0 || vh === 0) return;

      // Sync overlay canvas size to video display size
      const displayW = this.video.clientWidth;
      const displayH = this.video.clientHeight;
      if (this.overlay.width !== displayW || this.overlay.height !== displayH) {
        this.overlay.width = displayW;
        this.overlay.height = displayH;
      }

      const ctx = this.overlay.getContext('2d');
      ctx.clearRect(0, 0, displayW, displayH);

      // ── Crop detection ──
      const scale = ANALYSIS_WIDTH / vw;
      const aW = ANALYSIS_WIDTH;
      const aH = Math.round(vh * scale);

      this.analysisCanvas.width = aW;
      this.analysisCanvas.height = aH;
      const aCtx = this.analysisCanvas.getContext('2d');
      aCtx.drawImage(this.video, 0, 0, aW, aH);

      const imageData = aCtx.getImageData(0, 0, aW, aH);
      const cropRect = autoCrop(imageData);

      // Check if autoCrop returned full image (no receipt found)
      const isFullImage = cropRect.x === 0 && cropRect.y === 0 &&
                          cropRect.w === aW && cropRect.h === aH;

      if (!isFullImage) {
        // Scale crop rect to display coordinates
        const displayScale = displayW / vw;
        const targetRect = {
          x: (cropRect.x / scale) * displayScale,
          y: (cropRect.y / scale) * displayScale,
          w: (cropRect.w / scale) * displayScale,
          h: (cropRect.h / scale) * displayScale,
        };

        // Lerp smoothing
        if (this.smoothRect === null) {
          this.smoothRect = { ...targetRect };
        } else {
          this.smoothRect.x += (targetRect.x - this.smoothRect.x) * LERP_FACTOR;
          this.smoothRect.y += (targetRect.y - this.smoothRect.y) * LERP_FACTOR;
          this.smoothRect.w += (targetRect.w - this.smoothRect.w) * LERP_FACTOR;
          this.smoothRect.h += (targetRect.h - this.smoothRect.h) * LERP_FACTOR;
        }

        this._drawCropOverlay(ctx, displayW, displayH, this.smoothRect);
      } else {
        this.smoothRect = null;
      }

      // ── Ghost overlay ──
      if (this.ghostVisible) {
        this._drawGhostOverlay(ctx, displayW, displayH);
      }
    };

    this.animFrameId = requestAnimationFrame(loop);
  }

  _stopDetectionLoop() {
    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }
  }

  /**
   * Draw the crop boundary: green rounded rectangle with dimmed exterior.
   */
  _drawCropOverlay(ctx, canvasW, canvasH, rect) {
    const { x, y, w, h } = rect;
    const radius = 8;

    // Dim exterior
    ctx.save();
    ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
    ctx.beginPath();
    ctx.rect(0, 0, canvasW, canvasH);
    // Inner rect (counter-clockwise to cut out)
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.arcTo(x + w, y, x + w, y + radius, radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.arcTo(x + w, y + h, x + w - radius, y + h, radius);
    ctx.lineTo(x + radius, y + h);
    ctx.arcTo(x, y + h, x, y + h - radius, radius);
    ctx.lineTo(x, y + radius);
    ctx.arcTo(x, y, x + radius, y, radius);
    ctx.closePath();
    ctx.fill('evenodd');
    ctx.restore();

    // Green border
    ctx.save();
    ctx.strokeStyle = '#22c55e';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.arcTo(x + w, y, x + w, y + radius, radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.arcTo(x + w, y + h, x + w - radius, y + h, radius);
    ctx.lineTo(x + radius, y + h);
    ctx.arcTo(x, y + h, x, y + h - radius, radius);
    ctx.lineTo(x, y + radius);
    ctx.arcTo(x, y, x + radius, y, radius);
    ctx.closePath();
    ctx.stroke();
    ctx.restore();
  }

  /**
   * Draw the ghost overlay: bottom 20% of previous photo at top of viewfinder.
   */
  _drawGhostOverlay(ctx, canvasW, canvasH) {
    const lastPhoto = this.getLastPhoto();
    if (!lastPhoto) return;

    const photoW = lastPhoto.width;
    const photoH = lastPhoto.height;
    const ghostFrac = 0.2;
    const ghostSrcH = Math.round(photoH * ghostFrac);
    const ghostSrcY = photoH - ghostSrcH;

    // Scale to fill viewfinder width, proportional height
    const ghostDisplayH = Math.round((ghostSrcH / photoW) * canvasW);

    // Draw at 30% opacity
    ctx.save();
    ctx.globalAlpha = 0.3;
    ctx.drawImage(lastPhoto, 0, ghostSrcY, photoW, ghostSrcH, 0, 0, canvasW, ghostDisplayH);
    ctx.globalAlpha = 1;

    // Dashed line at bottom of ghost region
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 6]);
    ctx.beginPath();
    ctx.moveTo(0, ghostDisplayH);
    ctx.lineTo(canvasW, ghostDisplayH);
    ctx.stroke();
    ctx.setLineDash([]);

    // Small label
    ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
    ctx.font = '12px -apple-system, sans-serif';
    ctx.fillText('Align here', 8, ghostDisplayH - 6);
    ctx.restore();
  }
}
