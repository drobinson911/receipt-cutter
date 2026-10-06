import numpy as np

from receipt_bot import vendors
from receipt_bot.ocr import Line


def L(text, top, bottom):
    return Line(text, top, bottom, 0, 500, 90.0)


def test_detect_from_ocr_noise():
    assert vendors.detect(["FoodMax>x", "1160 Oroville Dam Blvd"]).name == "FoodMaxx"
    assert vendors.detect(["Food Maxx #474", "x"]).name == "FoodMaxx"
    assert vendors.detect(["COSTCO WHOLESALE", "#123"]).name == "Costco"
    assert vendors.detect(["Joe's Garage", "thanks"]) is None


def test_by_name_from_filename_vendor():
    assert vendors.by_name("FoodMaxx").name == "FoodMaxx"
    assert vendors.by_name("Food Maxx").name == "FoodMaxx"
    assert vendors.by_name("Unknown Diner") is None
    assert vendors.by_name(None) is None


def test_select_trim():
    assert vendors.select_trim("FoodMaxx") is vendors.foodmaxx_trim
    assert vendors.select_trim("Costco") is None
    assert vendors.select_trim("Some Store") is None


def _profile(h, spans):
    ink = np.zeros(h, dtype=int)
    for a, b in spans:
        ink[a:b + 1] = 50
    return ink


def test_foodmaxx_trim_cuts_above_separator_below_trx():
    lines = [L("TOTAL 1,451.25", 500, 530), L("Trx: 116 Term:9 Store:474 13:58:09", 900, 930),
             L("****************", 960, 980), L("We want to hear from you!", 1000, 1030), L("5% OFF", 1100, 1130)]
    ink = _profile(1500, [(l.top, l.bottom) for l in lines])
    row, why = vendors.foodmaxx_trim(None, ink, lines)
    assert 930 < row < 960 and row == (931 + 959) // 2, why


def test_foodmaxx_trim_without_banner_is_no_trim():
    lines = [L("TOTAL 9.99", 500, 530), L("Trx: 1", 900, 930)]
    row, why = vendors.foodmaxx_trim(None, _profile(1200, [(500, 530), (900, 930)]), lines)
    assert row is None and "no trim" in why


def test_foodmaxx_trim_refuses_to_cut_above_totals():
    lines = [L("We want to hear from you!", 300, 330), L("TOTAL 9.99", 500, 530)]
    row, why = vendors.foodmaxx_trim(None, _profile(800, [(300, 330), (500, 530)]), lines)
    assert row is None and "above the totals" in why
