# Visual Camera UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the native camera handoff with a custom getUserMedia viewfinder featuring real-time crop boundary detection and ghost overlap guide.

**Architecture:** New `js/camera-viewfinder.js` module handles all camera logic (stream, overlay rendering, capture). It imports `autoCrop` from `image-processing.js` for real-time crop detection. The viewfinder is a full-screen overlay with video + canvas layers. `capture-session.js` gets a new `addPhotoFromCanvas` method to accept captured frames directly. `index.html` gets a viewfinder HTML section, CSS, and wiring.

**Tech Stack:** getUserMedia API, Canvas API, requestAnimationFrame, existing autoCrop algorithm.

---

## File Structure

After implementation:

```
js/
  camera-viewfinder.js   (new — camera stream, crop overlay, ghost overlay, capture)
  capture-session.js     (modified — add addPhotoFromCanvas method)
  image-processing.js    (no changes)
  pdf-generator.js       (no changes)
index.html               (modified — viewfinder HTML/CSS, wire up camera buttons)
sw.js                    (modified — add camera-viewfinder.js to cache list)
```

### camera-viewfinder.js responsibilities:
- `openCamera()` — start getUserMedia stream, show viewfinder
- `closeCamera()` — stop stream, hide viewfinder
- `_startDetectionLoop()` — requestAnimationFrame at ~15fps running autoCrop on downsampled frames
- `_drawCropOverlay(rect)` — green rectangle with dimmed exterior, lerp smoothing
- `_drawGhostOverlay()` — semi-transparent previous photo bottom 20% at viewfinder top
- `_captureFrame()` — grab full-res frame from video, return as canvas
- `toggleFlash()` — torch on/off
- `toggleGhost()` — show/hide ghost overlay

---

### Task 1: Add `addPhotoFromCanvas` to CaptureSession

Allow the viewfinder to pass a captured frame directly as a canvas instead of going through File → FileReader → Image.

**Files:**
- Modify: `js/capture-session.js`

- [ ] **Step 1: Add `addPhotoFromCanvas` method**

Add this method to the `CaptureSession` class in `js/capture-session.js`, after the existing `addPhoto` method (after line 84):

```js
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

    // Create a placeholder image for originalImg (draw sourceCanvas to an image)
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
```

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/*.mjs`
Expected: All 14 tests pass.

- [ ] **Step 3: Commit**

```bash
git add js/capture-session.js
git commit -m "feat: add addPhotoFromCanvas method to CaptureSession"
```

---

### Task 2: Create Camera Viewfinder Module

The core camera module that handles getUserMedia, crop detection loop, ghost overlay, and frame capture.

**Files:**
- Create: `js/camera-viewfinder.js`

- [ ] **Step 1: Create `js/camera-viewfinder.js`**

```js
// js/camera-viewfinder.js

import { autoCrop } from './image-processing.js';

/**
 * Custom camera viewfinder with real-time crop detection and ghost overlay.
 *
 * Usage:
 *   const viewfinder = new CameraViewfinder({ video, overlayCanvas, onCapture, getLastPhoto });
 *   await viewfinder.open();
 *   viewfinder.close();
 */
export class CameraViewfinder {
  /**
   * @param {Object} options
   * @param {HTMLVideoElement} options.video - The video element to render the camera feed
   * @param {HTMLCanvasElement} options.overlayCanvas - Canvas layered on top of video for overlays
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
   * @returns {Promise<void>}
   * @throws {Error} if getUserMedia fails
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

    // Clear overlay
    const ctx = this.overlay.getContext('2d');
    ctx.clearRect(0, 0, this.overlay.width, this.overlay.height);
  }

  /**
   * Capture the current video frame as a full-resolution canvas.
   * Triggers a brief flash animation via CSS class.
   * @returns {HTMLCanvasElement}
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
   * @returns {boolean} New flash state
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
   * @returns {boolean} New ghost visibility state
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

      // Throttle to ~15fps
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
    // Outer rect (full canvas)
    ctx.rect(0, 0, canvasW, canvasH);
    // Inner rect (receipt area) — counter-clockwise to cut out
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
```

- [ ] **Step 2: Verify syntax**

Run: `cd /home/drobinson911/receipt-cutter && node -c js/camera-viewfinder.js`
Expected: No syntax errors.

- [ ] **Step 3: Commit**

```bash
git add js/camera-viewfinder.js
git commit -m "feat: add camera viewfinder module with crop detection and ghost overlay"
```

---

### Task 3: Add Viewfinder UI to index.html

Add the fullscreen viewfinder HTML section, CSS, and wire up the camera buttons to use the viewfinder instead of `<input capture>`.

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add viewfinder CSS**

Add these rules inside the `<style>` block, before the closing `</style>` tag (before line 363):

```css
    /* ─── Camera viewfinder ──────────────────────────────────────── */
    #viewfinder-section {
      display: none;
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: #000;
      z-index: 1000;
    }

    #viewfinder-section video {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    #viewfinder-overlay {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
    }

    .viewfinder-controls {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 24px;
      padding: 24px 16px;
      padding-bottom: max(24px, env(safe-area-inset-bottom));
      background: linear-gradient(transparent, rgba(0,0,0,0.6));
    }

    .viewfinder-top-controls {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 16px;
      padding-top: max(16px, env(safe-area-inset-top));
      background: linear-gradient(rgba(0,0,0,0.4), transparent);
    }

    .vf-btn {
      display: flex;
      align-items: center;
      justify-content: center;
      border: none;
      cursor: pointer;
      border-radius: 50%;
      color: #fff;
      background: rgba(255,255,255,0.2);
      backdrop-filter: blur(4px);
      -webkit-backdrop-filter: blur(4px);
    }

    .vf-btn-close {
      width: 40px;
      height: 40px;
      font-size: 1.2rem;
    }

    .vf-btn-flash, .vf-btn-ghost {
      width: 48px;
      height: 48px;
      font-size: 1.3rem;
    }

    .vf-btn-flash.active, .vf-btn-ghost.active {
      background: rgba(255,255,255,0.5);
    }

    .vf-btn-capture {
      width: 72px;
      height: 72px;
      background: #fff;
      border: 4px solid rgba(255,255,255,0.5);
    }

    .vf-btn-capture:active {
      transform: scale(0.9);
    }

    .vf-btn-capture-inner {
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: #fff;
    }

    .vf-photo-count {
      color: #fff;
      font-size: 0.85rem;
      font-weight: 600;
    }

    .vf-flash-effect {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: #fff;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.05s;
    }

    .vf-flash-effect.active {
      opacity: 0.8;
    }

    .vf-unavailable {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100%;
      color: #fff;
      text-align: center;
      padding: 20px;
    }

    .vf-unavailable p {
      margin-bottom: 12px;
    }
```

- [ ] **Step 2: Add viewfinder HTML section**

Add this inside `<main>`, just before the upload card (before line 373):

```html
    <!-- Camera viewfinder (fullscreen overlay) -->
    <div id="viewfinder-section">
      <video id="viewfinder-video" autoplay playsinline muted></video>
      <canvas id="viewfinder-overlay"></canvas>
      <div class="vf-flash-effect" id="vf-flash"></div>
      <div class="viewfinder-top-controls">
        <button class="vf-btn vf-btn-close" id="vf-close" title="Close camera">✕</button>
        <span class="vf-photo-count" id="vf-photo-count"></span>
      </div>
      <div class="viewfinder-controls">
        <button class="vf-btn vf-btn-flash" id="vf-flash-btn" title="Toggle flash" style="display:none">⚡</button>
        <button class="vf-btn vf-btn-capture" id="vf-capture" title="Take photo"><div class="vf-btn-capture-inner"></div></button>
        <button class="vf-btn vf-btn-ghost" id="vf-ghost-btn" title="Toggle overlap guide" style="display:none">👁</button>
      </div>
    </div>
```

- [ ] **Step 3: Update the `<script type="module">` block to wire up the viewfinder**

Add the viewfinder import at the top of the script (after line 442):

```js
    import { CameraViewfinder } from './js/camera-viewfinder.js';
```

Add viewfinder DOM refs after the existing DOM refs block (after line 475):

```js
    // ─── Viewfinder DOM refs ─────────────────────────────────────────────────
    const viewfinderSection = document.getElementById('viewfinder-section');
    const viewfinderVideo   = document.getElementById('viewfinder-video');
    const viewfinderOverlay = document.getElementById('viewfinder-overlay');
    const vfFlash           = document.getElementById('vf-flash');
    const vfClose           = document.getElementById('vf-close');
    const vfCapture         = document.getElementById('vf-capture');
    const vfFlashBtn        = document.getElementById('vf-flash-btn');
    const vfGhostBtn        = document.getElementById('vf-ghost-btn');
    const vfPhotoCount      = document.getElementById('vf-photo-count');
```

Add the viewfinder section to `allSections` — but actually the viewfinder is a fullscreen overlay and should NOT be in allSections. Instead, add a separate open/close pattern. Add this after the viewfinder DOM refs:

```js
    // ─── Camera Viewfinder ───────────────────────────────────────────────────
    let viewfinder = null;

    function updateVfPhotoCount() {
      const count = session.photos.length;
      vfPhotoCount.textContent = count > 0 ? `${count} photo${count !== 1 ? 's' : ''}` : '';
      // Show ghost toggle only when there are previous photos
      vfGhostBtn.style.display = count > 0 ? '' : 'none';
    }

    async function openViewfinder() {
      viewfinder = new CameraViewfinder({
        video: viewfinderVideo,
        overlayCanvas: viewfinderOverlay,
        onCapture: async (canvas) => {
          // Flash effect
          vfFlash.classList.add('active');
          setTimeout(() => vfFlash.classList.remove('active'), 150);

          await session.addPhotoFromCanvas(canvas);
          updateVfPhotoCount();
        },
        getLastPhoto: () => {
          const photos = session.photos;
          if (photos.length === 0) return null;
          return photos[photos.length - 1].croppedCanvas;
        },
      });

      try {
        await viewfinder.open();
        viewfinderSection.style.display = 'block';
        updateVfPhotoCount();

        // Show flash button if supported
        vfFlashBtn.style.display = viewfinder.flashSupported ? '' : 'none';
      } catch (err) {
        console.error('Camera failed:', err);
        viewfinder = null;
        // Fallback to file input
        inputCamera.click();
      }
    }

    function closeViewfinder() {
      if (viewfinder) {
        viewfinder.close();
        viewfinder = null;
      }
      viewfinderSection.style.display = 'none';

      // If we have photos, show session; otherwise show upload
      if (session.photos.length > 0) {
        showSection(sessionSection);
      } else {
        showSection(uploadCard);
      }
    }

    vfClose.addEventListener('click', closeViewfinder);

    vfCapture.addEventListener('click', () => {
      if (viewfinder) viewfinder.captureFrame();
    });

    vfFlashBtn.addEventListener('click', async () => {
      if (!viewfinder) return;
      const on = await viewfinder.toggleFlash();
      vfFlashBtn.classList.toggle('active', on);
    });

    vfGhostBtn.addEventListener('click', () => {
      if (!viewfinder) return;
      const visible = viewfinder.toggleGhost();
      vfGhostBtn.classList.toggle('active', visible);
    });
```

Now update the camera button handlers. Replace the `btnCamera` click handler (line 505) and the `btnAddPhoto` click handler (line 546):

Replace:
```js
    btnCamera.addEventListener('click', () => inputCamera.click());
```
With:
```js
    btnCamera.addEventListener('click', async () => {
      showSection(sessionSection);
      await openViewfinder();
    });
```

Replace:
```js
    btnAddPhoto.addEventListener('click', () => addCameraInput.click());
```
With:
```js
    btnAddPhoto.addEventListener('click', async () => {
      await openViewfinder();
    });
```

The `inputCamera` change handler (lines 508-513) stays as a fallback when getUserMedia fails and we fall back to `inputCamera.click()`.

- [ ] **Step 4: Verify syntax**

Run: `cd /home/drobinson911/receipt-cutter && node -e "import('./js/camera-viewfinder.js')" --input-type=module`
Expected: No errors (may warn about DOM APIs but no syntax errors).

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat: add camera viewfinder UI with crop boundary and ghost overlay"
```

---

### Task 4: Update Service Worker Cache

Add the new camera-viewfinder.js to the SW cache list.

**Files:**
- Modify: `sw.js`

- [ ] **Step 1: Add `camera-viewfinder.js` to LOCAL_ASSETS in `sw.js`**

Add `'/js/camera-viewfinder.js',` to the `LOCAL_ASSETS` array, after the existing JS files.

- [ ] **Step 2: Bump the cache version**

Change `const CACHE_NAME = 'receipt-cutter-v1';` to `const CACHE_NAME = 'receipt-cutter-v2';`

- [ ] **Step 3: Commit**

```bash
git add sw.js
git commit -m "chore: add camera-viewfinder.js to SW cache, bump cache version"
```

---

### Task 5: Integration Testing and Polish

Manual browser testing of the full viewfinder flow.

**Files:**
- Potentially any file from Tasks 1-4

- [ ] **Step 1: Test viewfinder opens on phone**

1. Serve the app: `cd /home/drobinson911/receipt-cutter && npx serve .`
2. Open on phone browser
3. Tap "Take Photo" — should request camera permission, then show fullscreen viewfinder
4. Verify video feed shows rear camera

- [ ] **Step 2: Test crop boundary overlay**

1. Point camera at a receipt on a dark surface
2. Verify green rectangle appears around the receipt
3. Move the camera — rectangle should follow smoothly (no jitter)
4. Point camera at a uniform surface (no receipt) — rectangle should disappear

- [ ] **Step 3: Test capture and ghost overlay**

1. Tap capture button — flash effect, photo count updates to "1 photo"
2. Ghost toggle button should appear
3. Move to next section of receipt — ghost overlay appears at top showing bottom of previous photo
4. Align receipt text with ghost, capture again
5. Verify photo count updates to "2 photos"
6. Toggle ghost off/on with eye button

- [ ] **Step 4: Test flash toggle**

1. On Android Chrome: flash button should appear, toggle torch on/off
2. On iOS Safari: flash button may be hidden (not supported) — verify it doesn't show

- [ ] **Step 5: Test close and session integration**

1. Close viewfinder — should return to session with captured photos
2. Verify photo thumbnails show in session list
3. "Done - Stitch & Convert" should work with viewfinder-captured photos
4. Full pipeline: viewfinder → session → stitch → PDF → download

- [ ] **Step 6: Test fallback for desktop/denied permissions**

1. On desktop browser: "Take Photo" should fall back to file picker if getUserMedia fails
2. Deny camera permission — should fall back to file picker
3. "Upload File" button should still work as before (unaffected by viewfinder changes)

- [ ] **Step 7: Fix any issues found and commit**

```bash
git add -A
git commit -m "fix: address integration testing issues for camera viewfinder"
```

- [ ] **Step 8: Run all unit tests**

Run: `cd /home/drobinson911/receipt-cutter && node --test tests/*.mjs`
Expected: All 14 tests pass.

- [ ] **Step 9: Final commit if needed**

```bash
git add -A
git commit -m "chore: final polish for camera viewfinder feature"
```
