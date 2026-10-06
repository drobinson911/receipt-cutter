---
name: headless_cutter_and_automation
description: Headless cutter tool + paused automation design for auto-cutting/naming receipts
metadata:
  type: project
---

**`tools/cut_receipt.py`** — a headless Python (Pillow+numpy) port of the app's `generatePdf` (js/pdf-generator.js + js/image-processing.js). Faithfully reproduces: `getRowBrightness`, `findCutPoints` (snap cuts to whitespace rows >240 within ±225px of each 3090px interval), `calcColumnsPerPage`, 300-DPI letter pages (2550×3300), strips pasted 1:1 (real size, never shrunk), centered columns. Usage: `python3 tools/cut_receipt.py IN.jpg OUT.pdf`. First real output: `20260703_Robinson_FoodMaxx.pdf` (2 pages, verified cuts land between text lines).

**Automation — BUILT 2026-10-06 (`receipt_bot/`, systemd user timer `receipt-bot.timer`, every 2 min).**
Scope per Donald (2026-10-06): exactly the manual procedure, nothing more. Poll `gdrive:ScanSnap/Receipts/` (top level) →
download → OCR (tesseract, whitespace strips) only for **store + date** (headless `claude -p` Sonnet on the first 2
strips only if OCR can't) → vendor trim rule → `tools/cut_receipt.py` → two checks: **no line sliced** (0 ink on every
cut row) and **no line dropped** (PDF rasterised back, each strip lifted from its column and every text band of the
trimmed scan must be inked at the same rows; no stray ink) → `Cut/YYYYMMDD_Robinson_Store.pdf`, original → `Done/`,
Discord "Receipt cut: <name>" + PDF. **No totals / item counts / card digits** (Donald: "just cut the receipt like we have been").
Failure → `Needs-Review/` + "⚠️ Receipt needs attention: <file> — <reason>; Claude is on it" + a job in `~/uas-ops/queue/`
for the forge ops responder (Receipts playbook in `~/uas-ops/RESPONDER.md`; it fixes via `python -m receipt_bot retry NAME
[--vendor/--date/--trim-row/--no-trim/--search-range]`, code fixes only via `tools/responder-fix.sh` = tests gate the merge).
State `~/.local/state/receipt-bot/state.json` (by Drive file ID; never reprocessed). Tests: `.venv/bin/python -m pytest tests/py`
(real-receipt fixture lives OUTSIDE git at `~/.local/share/receipt-bot/fixtures/` — the GitHub repo is PUBLIC, never commit scans).
