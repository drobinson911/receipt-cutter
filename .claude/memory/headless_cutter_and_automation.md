---
name: headless_cutter_and_automation
description: Headless cutter tool + paused automation design for auto-cutting/naming receipts
metadata:
  type: project
---

**`tools/cut_receipt.py`** — a headless Python (Pillow+numpy) port of the app's `generatePdf` (js/pdf-generator.js + js/image-processing.js). Faithfully reproduces: `getRowBrightness`, `findCutPoints` (snap cuts to whitespace rows >240 within ±225px of each 3090px interval), `calcColumnsPerPage`, 300-DPI letter pages (2550×3300), strips pasted 1:1 (real size, never shrunk), centered columns. Usage: `python3 tools/cut_receipt.py IN.jpg OUT.pdf`. First real output: `20260703_Robinson_FoodMaxx.pdf` (2 pages, verified cuts land between text lines).

**Automation design — PAUSED** (Donald: "getting too deep, continue later"). Requirements gathered so far for an auto-cut+auto-name pipeline:
- Trigger: **fully automatic** (watch a folder for new scans)
- Storage: **Google Drive** — Claude HAS a working Drive connector (drobinson911@gmail.com), NO OneDrive connector. Moving scans to Drive lets the always-on iMac bot do everything without the gaming PC being on. See [[receipts_source_folder]].
- Naming: `YYYYMMDD_Robinson_Store` — **name always "Robinson"** (Donald edits the rare exception); date + store read off the receipt.
- Output constraints (HARD): every purchase line included; cut ONLY between text lines; US-Letter; **2 columns**; however many pages; **real size or larger, NEVER shrunk**.
- Multiple purchasers exist but default-to-Robinson chosen, so no card→name lookup.
- STILL OPEN when resuming: (Q4) sharing scope for other purchasers — self-serve hosted PWA link vs. auto-pipeline for their scans vs. both; and the cut engine — Claude-in-the-loop reading each receipt for date/store vs. pure OCR (tesseract).

Process note: this is mid-`brainstorming` skill. Resume by finishing clarifiers → propose approaches → design doc → writing-plans. Do NOT build the watcher/pipeline before design approval.
