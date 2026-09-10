---
name: foodmaxx_trim_rule
description: FoodMaxx receipts — trim the footer before cutting to PDF
metadata:
  type: project
---

**FoodMaxx receipt rule (per Donald, confirmed 2026-07-05):** before running the cut, **trim off the survey/coupon footer**. Cut in the whitespace band **directly above the `**** We want to hear from you!` line** (i.e. just after the `Trx:… Term:… Store:…` line) and **discard everything below it**.

What gets discarded: the `****…` separator, `We want to hear from you!` survey block, the `5% OFF` coupon, the invitation code, the Spanish repeat, and `Contact Customer Care`.

What's KEPT: everything through the payment/card slip — all line items, `SUBTOTAL / TOTAL TAX / TOTAL`, `Visa TENDER / Acct ••NNNN / APPRVL CODE / Cas Ref#`, `NUMBER OF ITEMS`, the `Special Purchase Discount / YOU SAVED / THAT IS A SAVINGS` lines, the duplicate `Food Maxx #___` card slip (`VISA CREDIT / AID / TVR / TC / RRN …`), `Total: USD$ …`, `THANK YOU FOR SHOPPING AT FOOD MAXX!`, and `Trx:… Term:… Store:…`. Donald wants the card slip retained.

Implementation for now: crop the source scan to `[0 : cutRow)` where cutRow is the brightest (whitest) row in the gap just above the `****`/`We want to hear from you!` banner, then run `tools/cut_receipt.py`. For the FoodMaxx 07/03/2026 scan (950×9412) that cut row was ~7479 (banner started ~7530). When the automation is built (see [[headless_cutter_and_automation]]), this footer-trim should be a per-vendor rule — detect the `We want to hear from you!` / `****` banner and cut just above it.
