import numpy as np
import pytest
from PIL import Image, ImageDraw

import cut_receipt
from receipt_bot import pipeline, verify


def _cut(img, tmp_path, name="o.pdf", **kw):
    pdf = str(tmp_path / name)
    return cut_receipt.cut(img, pdf, log=lambda *a: None, **kw), pdf


def test_clean_cut_passes_both_checks(receipt_img, tmp_path):
    geom, pdf = _cut(receipt_img, tmp_path)
    verify.check_sliced(geom, pdf)
    facts = verify.check_dropped(receipt_img, geom, pdf, str(tmp_path))
    assert facts["lines_scan"] == facts["lines_pdf"] > 200


def test_sliced_line_is_caught(tmp_path):
    from conftest import synthetic_receipt
    geom, pdf = _cut(synthetic_receipt(top=3090 - 34 * 90), tmp_path, search=0)  # row 3090 = a line's first row   # cuts forced onto fixed rows
    assert any(ink for _, ink in geom["ink_on_cuts"])
    with pytest.raises(verify.CutCheckError, match="slices a text line"):
        verify.check_sliced(geom, pdf)


def test_dropped_line_is_caught(receipt_img, tmp_path):
    damaged = receipt_img.copy()
    ImageDraw.Draw(damaged).rectangle((0, 4000, damaged.width, 4040), fill=255)   # a line vanishes from the PDF
    geom, pdf = _cut(damaged, tmp_path)
    with pytest.raises(verify.CutCheckError, match="missing from the PDF"):
        verify.check_dropped(receipt_img, geom, pdf, str(tmp_path))


def test_foreign_ink_is_caught(receipt_img, tmp_path):
    a = np.asarray(receipt_img)
    gaps = [y for y in range(1000, 2000) if (a[y] < 140).sum() == 0]
    y = gaps[len(gaps) // 2]
    noisy = receipt_img.copy()
    ImageDraw.Draw(noisy).rectangle((20, y - 2, 400, y + 2), fill=0) if gaps else None
    geom, pdf = _cut(noisy, tmp_path)
    with pytest.raises(verify.CutCheckError):
        verify.check_dropped(receipt_img, geom, pdf, str(tmp_path))


def test_strips_must_tile_the_scan(receipt_img, tmp_path):
    geom, pdf = _cut(receipt_img, tmp_path)
    bad = dict(geom, cuts=geom["cuts"][:-1] + [geom["cuts"][-1] - 50])
    with pytest.raises(verify.CutCheckError, match="tile"):
        verify.check_dropped(receipt_img, bad, pdf, str(tmp_path))


def test_page_count_mismatch_is_caught(receipt_img, tmp_path):
    geom, pdf = _cut(receipt_img, tmp_path)
    with pytest.raises(verify.CutCheckError, match="pages"):
        verify.check_sliced(dict(geom, pages=geom["pages"] + 1), pdf)


def test_all_black_export_bug_is_rejected():
    with pytest.raises(pipeline.ScanError, match="all-black.*std dev 0"):
        pipeline.check_image(Image.new("L", (900, 5000), 0))


def test_blank_and_tiny_images_rejected():
    with pytest.raises(pipeline.ScanError, match="blank"):
        pipeline.check_image(Image.new("L", (900, 5000), 255))
    with pytest.raises(pipeline.ScanError, match="too small"):
        pipeline.check_image(Image.new("L", (50, 50), 128))


def test_unopenable_file_is_scan_error(tmp_path):
    p = tmp_path / "x.jpg"
    p.write_bytes(b"not a jpeg")
    with pytest.raises(pipeline.ScanError, match="can't be opened"):
        pipeline.load_image(str(p), str(tmp_path))
