from app.services.menu_import import _clean_ocr_line, _looks_like_category, _parse_price_line


def test_parse_common_indian_menu_price():
    assert _parse_price_line("Paneer Tikka ₹249") == ("Paneer Tikka", 249.0)
    assert _parse_price_line("Chicken Biryani Rs. 299") == ("Chicken Biryani", 299.0)
    assert _parse_price_line("Veg Noodles 180") == ("Veg Noodles", 180.0)


def test_parse_rejects_non_price_lines():
    assert _parse_price_line("Paneer Tikka") is None
    assert _parse_price_line("Call 9876543210") is None


def test_category_detection():
    assert _looks_like_category("STARTERS")
    assert _looks_like_category("Main Course")
    assert not _looks_like_category("Paneer Tikka 249")


def test_ocr_line_cleanup():
    assert _clean_ocr_line("  •  Paneer Tikka  ₹249  ") == "Paneer Tikka ₹249"
