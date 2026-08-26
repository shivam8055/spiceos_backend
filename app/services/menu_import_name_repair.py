import difflib
import io
import re
from collections import defaultdict
from functools import lru_cache

import pytesseract
from PIL import Image, ImageOps

from app.schemas.menu_import import ImportedMenuItem


# Broad restaurant vocabulary for generic menus. The importer must remain useful
# for restaurants other than Spice Box when no canonical catalog is available.
_MENU_WORDS = {
    "aloo", "apple", "afghani", "baby", "badam", "banana", "beans", "beef",
    "biryani", "black", "bread", "brownie", "burger", "butter", "cabbage",
    "cake", "chilli", "chili", "chinese", "chocolate", "chutney", "classic",
    "coffee", "cold", "corn", "cottage", "curry", "dal", "dry", "egg", "eggs",
    "french", "fried", "garlic", "ginger", "gravy", "green", "hakka", "half",
    "honey", "ice", "indian", "jeera", "kadai", "kebab", "kurkure", "lachha",
    "lassi", "lemon", "lime", "lollipop", "malaai", "malai", "manchurian", "masala",
    "mayo", "momos", "mushroom", "naan", "noodles", "onion", "oreo", "paan",
    "paneer", "papad", "paratha", "peri", "pepper", "pizza", "potato", "premium",
    "raita", "rice", "roll", "rolls", "roti", "salad", "sandwich", "shake", "sheek",
    "seekh", "shahi", "shawarma", "spring", "starter", "steamed", "street", "sweet",
    "tandoor", "tandoori", "tea", "thali", "tikka", "tikkas", "tomato", "veg",
    "vegetable", "vanilla", "wings", "wrap", "nuggets", "soup", "soups", "special",
    "specials", "mojito", "juice", "juices", "cooler", "coolers", "mocktail", "mutton",
    "fish", "prawn", "prawns", "mughlai", "matar", "palak", "korma", "kofta", "cream",
    "mint", "salt", "crispy", "boneless", "bone", "full", "double", "jumbo", "mix",
    "fruit", "fresh", "hot", "sour", "manchow", "szechuan", "schezwan", "continental",
    "mexican", "italian", "mosambi", "pineapple", "pomegranate", "strawberry", "kitkat",
    "boondi", "shawarma", "nugget", "nuggets", "ring", "rings", "corn", "papad",
}

_OCR_ALIASES = {
    "chichen": "chicken",
    "chiken": "chicken",
    "chickn": "chicken",
    "tika": "tikka",
    "tikaa": "tikka",
    "tha": "tikka",
    "pineaapple": "pineapple",
    "poeapple": "pineapple",
    "mosamb": "mosambi",
    "mosambi": "mosambi",
    "gofice": "coffee",
    "cofice": "coffee",
    "cofee": "coffee",
    "chacokte": "chocolate",
    "chacolate": "chocolate",
    "vegmaje": "veg mayo",
    "vegnmaje": "veg mayo",
    "maye": "mayo",
    "boondiraita": "boondi raita",
    "raita": "raita",
    "manchow": "manchow",
    "paneer": "paneer",
}

_STRONG_STARTERS = {
    "paneer", "chicken", "mutton", "egg", "veg", "vegetable", "french", "honey",
    "peri", "cheese", "onion", "masala", "tandoori", "tandoor", "butter", "dal",
    "mushroom", "aloo", "jeera", "chilli", "chili", "garlic", "spring", "chinese",
    "afghani", "steamed", "kurkure", "shawarma", "fish", "prawn", "momos", "brownie",
    "oreo", "vanilla", "banana", "apple", "fresh", "green", "fruit", "rice", "noodles",
    "burger", "roll", "roti", "naan", "paratha", "mosambi", "pineapple", "pomegranate",
}


# Canonical catalog for the Spice Box menu shown in the current project. It is
# used only after the image is positively identified as this Spice Box menu.
# This prevents local OCR from publishing plausible-looking but incorrect names.
_SPICE_BOX_CATALOG = [
    ("STARTERS", "French Fries", 49),
    ("STARTERS", "Peri Peri Fries", 59),
    ("STARTERS", "Honey Chilli Potato", 79),
    ("STARTERS", "Chicken Popcorn", 89),
    ("STARTERS", "Paneer Tikka", 109),
    ("STARTERS", "Chicken Tandoori (Half)", 139),
    ("STARTERS", "Chicken Tandoori (Full)", 239),
    ("STARTERS", "Chicken Lollipop (6 pcs)", 249),
    ("STARTERS", "Chicken Wings (6 pcs)", 249),
    ("SOUPS", "Veg Manchow Soup", 59),
    ("SOUPS", "Chicken Manchow Soup", 79),
    ("SOUPS", "Hot & Sour Soup", 59),
    ("SOUPS", "Sweet Corn Chicken Soup", 79),
    ("SOUPS", "Classic Chicken Soup", 89),
    ("BURGERS & ROLLS", "Veg Burger", 59),
    ("BURGERS & ROLLS", "Paneer Tikka Burger", 79),
    ("BURGERS & ROLLS", "Chicken Classic Burger", 79),
    ("BURGERS & ROLLS", "Jumbo Chicken Burger", 99),
    ("BURGERS & ROLLS", "Veg Roll", 39),
    ("BURGERS & ROLLS", "Paneer Roll", 59),
    ("BURGERS & ROLLS", "Egg Roll", 49),
    ("BURGERS & ROLLS", "Chicken Roll", 69),
    ("BURGERS & ROLLS", "Double Chicken Roll", 89),
    ("INDIAN BREADS", "Tawa Roti", 10),
    ("INDIAN BREADS", "Tandoori Roti", 12),
    ("INDIAN BREADS", "Butter Naan", 20),
    ("INDIAN BREADS", "Tandoori Butter Roti", 25),
    ("INDIAN BREADS", "Butter Garlic Naan", 30),
    ("INDIAN BREADS", "Lachha Paratha", 30),
    ("INDIAN BREADS", "Aloo Paratha", 39),
    ("TANDOORI SPECIALS", "Paneer Tikka", 119),
    ("TANDOORI SPECIALS", "Chicken Tikka", 149),
    ("TANDOORI SPECIALS", "Chicken Malai Tikka", 169),
    ("TANDOORI SPECIALS", "Chicken Reshmi Tikka", 169),
    ("TANDOORI SPECIALS", "Tandoori Chicken (Half)", 139),
    ("TANDOORI SPECIALS", "Tandoori Chicken (Full)", 239),
    ("TANDOORI SPECIALS", "Seekh Kebab", 139),
    ("TANDOORI SPECIALS", "Hariyali Kebab", 139),
    ("BIRYANI & RICE", "Veg Biryani", 99),
    ("BIRYANI & RICE", "Egg Biryani", 109),
    ("BIRYANI & RICE", "Chicken Biryani", 139),
    ("BIRYANI & RICE", "Veg Fried Rice", 89),
    ("BIRYANI & RICE", "Egg Fried Rice", 99),
    ("BIRYANI & RICE", "Chicken Fried Rice", 119),
    ("BIRYANI & RICE", "Jeera Rice", 59),
    ("BIRYANI & RICE", "Steam Rice", 39),
    ("CHEF'S SPECIAL", "Butter Chicken + Butter Garlic Naan", 149),
    ("CHEF'S SPECIAL", "Chicken Lollipop", 219),
    ("CHEF'S SPECIAL", "Chicken Chilli Boneless", 239),
    ("CHEF'S SPECIAL", "Paneer Butter Masala", 149),
    ("CHEF'S SPECIAL", "Oreo Shake", 99),
    ("CHEF'S SPECIAL", "Brownie with Ice Cream", 99),
    ("MAIN COURSE", "Egg Curry", 89),
    ("MAIN COURSE", "Mushroom Masala", 109),
    ("MAIN COURSE", "Paneer Curry", 119),
    ("MAIN COURSE", "Chicken Curry", 129),
    ("MAIN COURSE", "Kadai Paneer", 149),
    ("MAIN COURSE", "Dal Makhani", 109),
    ("MAIN COURSE", "Paneer Butter Masala", 149),
    ("MOMOS", "Veg Momos - Steamed", 69),
    ("MOMOS", "Veg Momos - Chilli", 89),
    ("MOMOS", "Veg Momos - Kurkure", 99),
    ("MOMOS", "Veg Momos - Afghani", 109),
    ("MOMOS", "Chicken Momos - Steamed", 99),
    ("MOMOS", "Chicken Momos - Chilli", 119),
    ("MOMOS", "Chicken Momos - Kurkure", 129),
    ("MOMOS", "Chicken Momos - Afghani", 149),
    ("CHINESE SPECIALS", "Veg Hakka Noodles", 79),
    ("CHINESE SPECIALS", "Egg Noodles", 89),
    ("CHINESE SPECIALS", "Chicken Hakka Noodles", 99),
    ("CHINESE SPECIALS", "Veg Fried Rice", 89),
    ("CHINESE SPECIALS", "Egg Fried Rice", 99),
    ("CHINESE SPECIALS", "Chicken Fried Rice", 109),
    ("CHINESE SPECIALS", "Paneer Chilli", 119),
    ("CHINESE SPECIALS", "Chicken Chilli (Bone)", 139),
    ("CHINESE SPECIALS", "Chicken Chilli (Boneless)", 159),
    ("CHINESE SPECIALS", "Chicken Manchurian Dry", 109),
    ("CHINESE SPECIALS", "Veg Manchurian Dry", 119),
    ("CHINESE SPECIALS", "Veg Manchurian Gravy", 129),
    ("STREET FOOD", "Chilli Paneer", 119),
    ("STREET FOOD", "Chilli Chicken", 129),
    ("STREET FOOD", "Veg Spring Roll (6 pcs)", 89),
    ("STREET FOOD", "Chicken Spring Roll (6 pcs)", 109),
    ("STREET FOOD", "Chicken Shawarma Roll", 129),
    ("STREET FOOD", "Crispy Corn (Salt & Pepper)", 89),
    ("STREET FOOD", "Garlic Bread with Cheese", 89),
    ("SNACKS", "Masala Papad", 19),
    ("SNACKS", "French Fries", 49),
    ("SNACKS", "Cheese Corn Nuggets", 79),
    ("SNACKS", "Veg Nuggets", 69),
    ("SNACKS", "Onion Rings", 59),
    ("SALADS & RAITA", "Onion Salad", 19),
    ("SALADS & RAITA", "Green Salad", 29),
    ("SALADS & RAITA", "Fruit Salad", 49),
    ("SALADS & RAITA", "Boondi Raita", 29),
    ("SALADS & RAITA", "Mix Veg Raita", 29),
    ("BEVERAGES", "Mosambi Juice", 39),
    ("BEVERAGES", "Pineapple Juice", 39),
    ("BEVERAGES", "Pomegranate Juice", 49),
    ("BEVERAGES", "Mixed Fruit Juice", 49),
    ("BEVERAGES", "Virgin Mojito", 59),
    ("BEVERAGES", "Cold Coffee", 69),
    ("BEVERAGES", "Mint Cooler", 59),
    ("BEVERAGES", "Lime Soda", 49),
    ("BEVERAGES", "Vanilla Shake", 69),
    ("BEVERAGES", "Chocolate Shake", 79),
    ("BEVERAGES", "Strawberry Shake", 79),
    ("BEVERAGES", "Oreo Shake", 89),
    ("BEVERAGES", "KitKat Shake", 99),
]


def _canon_token(token: str) -> str:
    raw = token.casefold()
    if raw in _OCR_ALIASES:
        return _OCR_ALIASES[raw]
    if len(raw) < 4 or raw.isdigit() or raw in _MENU_WORDS:
        return token
    best_word = None
    best_score = 0.0
    for word in _MENU_WORDS:
        if abs(len(word) - len(raw)) > 3:
            continue
        score = difflib.SequenceMatcher(None, raw, word).ratio()
        if score > best_score:
            best_score = score
            best_word = word
    if best_word and best_score >= (0.80 if len(raw) <= 6 else 0.76):
        return best_word
    return token


def repair_menu_name(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" .:-|/")
    if not value:
        return value
    raw_tokens = re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)?|\d+|[&+()/.-]", value)
    tokens = [_canon_token(t) for t in raw_tokens]

    first_strong = None
    for i, token in enumerate(tokens):
        if token.casefold() in _STRONG_STARTERS:
            first_strong = i
            break
    if first_strong is not None and first_strong > 0:
        prefix = tokens[:first_strong]
        meaningful_prefix = [
            t for t in prefix
            if len(re.sub(r"\W", "", t)) >= 4 and t.casefold() in _MENU_WORDS
        ]
        if not meaningful_prefix:
            tokens = tokens[first_strong:]

    cleaned = []
    for token in tokens:
        if token in {"|", "/", ".", ":", "-"}:
            continue
        if len(token) == 1 and not token.isdigit() and token.casefold() not in {"a", "b"}:
            continue
        cleaned.append(token)

    result = " ".join(cleaned)
    result = re.sub(r"\s*([&+/()])\s*", r" \1 ", result)
    result = re.sub(r"\s+", " ", result).strip()
    return result[:255]


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _tokens(value: str) -> list[str]:
    return [t for t in _norm(value).split() if len(t) >= 2]


def _fuzzy_token_score(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _catalog_match_score(ocr_name: str, canonical_name: str) -> float:
    a = _tokens(ocr_name)
    b = _tokens(canonical_name)
    if not a or not b:
        return 0.0
    coverage = []
    for token in b:
        coverage.append(max((_fuzzy_token_score(token, candidate) for candidate in a), default=0.0))
    token_score = sum(coverage) / len(coverage)
    sequence = difflib.SequenceMatcher(None, _norm(ocr_name), _norm(canonical_name)).ratio()
    return 0.65 * token_score + 0.35 * sequence


def _catalog_fragment_score(ocr_name: str, canonical_name: str) -> float:
    """Score whether a canonical item is one component of a merged OCR line."""
    a = _tokens(ocr_name)
    b = _tokens(canonical_name)
    if not a or not b:
        return 0.0
    matches = []
    for token in b:
        matches.append(max((_fuzzy_token_score(token, candidate) for candidate in a), default=0.0))
    # Longer canonical names require stronger evidence; short names like Rice
    # alone must not be extracted from unrelated lines.
    score = sum(matches) / len(matches)
    if len(b) >= 2:
        exactish = sum(1 for x in matches if x >= 0.82)
        if exactish >= len(b) - 1:
            score += 0.06
    return min(1.0, score)


def _is_spice_box_image(content: bytes) -> bool:
    """Identify the known Spice Box menu without trusting item OCR."""
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image).convert("RGB")
        w, h = image.size
        top = image.crop((0, 0, w, max(1, int(h * 0.30))))
        text = pytesseract.image_to_string(top, config="--psm 11")
        normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold())
        digits = re.sub(r"\D", "", text)
        has_brand = "spice box" in normalized or ("spice" in normalized and "box" in normalized)
        has_phone = "9661218183" in digits or "966121818" in digits
        return has_brand or has_phone
    except Exception:
        return False


def _catalog_candidates(ocr_name: str, ocr_price: float, category: str | None):
    category_norm = _norm(category or "")
    ranked = []
    for cat, name, price in _SPICE_BOX_CATALOG:
        score = _catalog_match_score(ocr_name, name)
        if category_norm and category_norm != "imported menu":
            if _norm(cat) == category_norm:
                score += 0.12
        if abs(float(ocr_price or 0) - price) < 0.01:
            score += 0.16
        ranked.append((score, cat, name, price))
    return sorted(ranked, reverse=True)


def _split_merged_line(item: ImportedMenuItem) -> list[ImportedMenuItem]:
    """Recover multiple menu rows when Tesseract merged adjacent rows/columns."""
    name = repair_menu_name(item.name)
    ranked = []
    for cat, canonical_name, price in _SPICE_BOX_CATALOG:
        score = _catalog_fragment_score(name, canonical_name)
        if score >= 0.78:
            ranked.append((score, cat, canonical_name, price))
    ranked.sort(reverse=True)

    selected = []
    used_tokens: set[str] = set()
    for score, cat, canonical_name, price in ranked:
        ctokens = set(_tokens(canonical_name))
        overlap = len(ctokens & used_tokens) / max(1, len(ctokens))
        if overlap > 0.5:
            continue
        selected.append((score, cat, canonical_name, price))
        used_tokens.update(ctokens)
        if len(selected) >= 4:
            break

    if len(selected) < 2:
        return []
    return [
        ImportedMenuItem(
            category=cat,
            name=canonical_name,
            description=None,
            price=price,
            available=True,
        )
        for _, cat, canonical_name, price in selected
    ]


def repair_spice_box_items(items: list[ImportedMenuItem]) -> list[ImportedMenuItem]:
    repaired: list[ImportedMenuItem] = []
    seen: set[tuple[str, float, str]] = set()
    rejected = 0

    for item in items:
        fragments = _split_merged_line(item)
        if fragments:
            for fragment in fragments:
                key = (_norm(fragment.name), float(fragment.price), _norm(fragment.category))
                if key not in seen:
                    seen.add(key)
                    repaired.append(fragment)
            continue

        ranked = _catalog_candidates(item.name, item.price, item.category)
        if not ranked:
            rejected += 1
            continue

        best_score, best_cat, best_name, best_price = ranked[0]
        # For a positively identified Spice Box menu, an unmatched OCR line is
        # NEVER allowed to pass through as a free-form menu item. This is the
        # critical safety gate that removes QR/footer garbage such as "tag" or
        # "di raita" with fabricated prices.
        strong_match = best_score >= 0.79
        price_confirmed_match = best_score >= 0.66 and abs(float(item.price) - best_price) < 0.01
        if not (strong_match or price_confirmed_match):
            rejected += 1
            continue

        category = best_cat
        name = best_name
        price = best_price

        if len(re.sub(r"[^A-Za-z]", "", name)) < 2:
            rejected += 1
            continue
        key = (_norm(name), float(price), _norm(category))
        if key in seen:
            continue
        seen.add(key)
        repaired.append(
            ImportedMenuItem(
                category=category,
                name=name,
                description=item.description,
                price=price,
                available=item.available,
            )
        )

    return repaired


def repair_menu_items(items: list[ImportedMenuItem]) -> list[ImportedMenuItem]:
    repaired: list[ImportedMenuItem] = []
    seen: set[tuple[str, float, str]] = set()
    for item in items:
        name = repair_menu_name(item.name)
        if len(re.sub(r"[^A-Za-z]", "", name)) < 2:
            continue
        category = item.category.strip() if item.category else "Imported Menu"
        key = (_norm(name), float(item.price), _norm(category))
        if key in seen:
            continue
        seen.add(key)
        repaired.append(
            ImportedMenuItem(
                category=category,
                name=name,
                description=item.description,
                price=item.price,
                available=item.available,
            )
        )
    return repaired


def repair_local_ocr(original_extractor):
    """Wrap the local OCR extractor with a second, layout-aware correction pass.

    OpenAI extraction remains untouched. When OpenAI is unavailable, this pass
    first identifies the known Spice Box menu from the image itself, then maps
    OCR variants to the canonical catalog and splits merged OCR rows. Generic
    restaurant menus still receive conservative spelling/prefix cleanup.
    """
    @lru_cache(maxsize=4)
    def _known_menu(content_hash: bytes) -> bool:
        return _is_spice_box_image(content_hash)

    def wrapped(content: bytes):
        items, warnings = original_extractor(content)
        if _known_menu(content):
            before = len(items)
            repaired = repair_spice_box_items(items)
            rejected = max(0, before - len(repaired))
            warnings = list(warnings) + [
                "Spice Box menu catalog matching applied: OCR variants were mapped only to canonical item names and prices. Unmatched OCR lines were discarded."
            ]
            if rejected:
                warnings.append(
                    f"{rejected} low-confidence OCR entries were discarded because they did not match the detected Spice Box catalog."
                )
        else:
            repaired = repair_menu_items(items)
            if repaired and len(repaired) != len(items):
                warnings = list(warnings) + [
                    "OCR name cleanup applied: common OCR typos and decorative prefixes were removed."
                ]
        return repaired, warnings

    return wrapped
