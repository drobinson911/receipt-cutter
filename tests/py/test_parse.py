import datetime as dt

from receipt_bot import parse

TODAY = dt.date(2026, 10, 6)


def test_filename_date_only():
    sn = parse.parse_scan_filename("10062026.jpg")
    assert sn.date == dt.date(2026, 10, 6) and sn.vendor is None and sn.ext == ".jpg"


def test_filename_with_vendor_and_dupe_suffixes():
    assert parse.parse_scan_filename("10062026_FoodMaxx.jpg").vendor == "FoodMaxx"
    sn = parse.parse_scan_filename("07032026_Food Maxx (1).JPEG")
    assert sn.date == dt.date(2026, 7, 3) and sn.vendor == "Food Maxx" and sn.ext == ".jpeg"
    assert parse.parse_scan_filename("10062026-1.jpg").vendor is None   # rclone dedupe rename


def test_filename_invalid_or_foreign():
    assert parse.parse_scan_filename("13452026.jpg").date is None       # month 13
    assert parse.parse_scan_filename("scan.pdf") == parse.ScanName(None, None, ".pdf")


def test_is_receipt_file():
    assert parse.is_receipt_file("a.JPG") and parse.is_receipt_file("b.pdf") and parse.is_receipt_file("c.png")
    assert not parse.is_receipt_file("notes.txt") and not parse.is_receipt_file(".hidden.jpg")


def test_store_slug_and_pdf_name():
    assert parse.store_slug("Food Maxx #474") == "FoodMaxx"
    assert parse.store_slug("FoodMaxx") == "FoodMaxx"
    assert parse.store_slug("HOME DEPOT") == "HomeDepot"
    assert parse.store_slug("Trader Joe's") == "TraderJoes"
    assert parse.output_pdf_name(dt.date(2026, 10, 6), "FoodMaxx") == "20261006_Robinson_FoodMaxx.pdf"


def test_find_dates_formats_and_plausibility():
    t = "10/06/26 13:49:33\n2026-10-05\nOct 4, 2026\n10/06/2026 13:58\n12/25/2031\n01/01/19"
    assert parse.find_dates(t, TODAY) == [dt.date(2026, 10, 6), dt.date(2026, 10, 5), dt.date(2026, 10, 4), dt.date(2026, 10, 6)]
    assert parse.find_dates("530 533-2389  Store:474  1/2", TODAY) == []


def test_choose_date():
    d6, d5 = dt.date(2026, 10, 6), dt.date(2026, 10, 5)
    assert parse.choose_date([d5, d6, d6], d6) == (d6, "ocr+filename")
    assert parse.choose_date([d5, d5, d6], None) == (d5, "ocr")
    assert parse.choose_date([], d6) == (d6, "filename")
    assert parse.choose_date([], None) == (None, "none")
