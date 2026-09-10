---
name: receipts_source_folder
description: Where scanned receipts land and how Claude on the iMac reaches them
metadata:
  type: reference
---

Donald scans receipts with a **ScanSnap** scanner on his Windows gaming PC. They land in OneDrive:

- Main scan folder (Windows path): `C:\Users\drobi\OneDrive\ScanSnap`
- Receipts specifically: `C:\Users\drobi\OneDrive\ScanSnap\Receipts`

**How to access from the iMac** (where the Claude Discord bot runs): the gaming PC's C: drive is visible through WSL on `build-server`. So:

```
ssh build-server 'ls -lt "/mnt/c/Users/drobi/OneDrive/ScanSnap/Receipts"'
```

Pull a receipt over to read it:
```
scp build-server:'/mnt/c/Users/drobi/OneDrive/ScanSnap/Receipts/<file>' /local/path
```

Filenames are roughly `MMDDYYYY_Vendor.jpg` (or `.pdf`). Reading receipts: they scan as very tall images — slice into full-width horizontal strips (~1300px tall) with ImageMagick, then Read each strip so the text is legible. PDFs can be Read directly.

Note: the **Receipt Cutter PWA** (this repo) is a separate capture/stitch tool. Its stitched *export sometimes comes out all-black* (a blank JPEG, mean≈0, std dev 0) — that's an export bug, not a bad photo. If a receipt image is uniformly black, ask for the ScanSnap scan from the Receipts folder instead. See [[receipt_export_black_bug]] if/when that bug is investigated.
