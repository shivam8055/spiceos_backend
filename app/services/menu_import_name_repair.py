import difflib
import re
from collections import defaultdict

from app.schemas.menu_import import ImportedMenuItem


# Common restaurant/menu vocabulary. This is deliberately broad so the repair
# works for arbitrary restaurant menus rather than being tied to Spice Box.
_MENU_WORDS = {
    "aloo", "apple", "afghani", "baby", "badam", "banana", "beans", "beef",
    "biryani", "black", "bread", "brownie", "burger", "butter", "cabbage",
    "cake", "chilli", "chili", "chicken", "cheese", "chinese", "choco",
    "chocolate", "chutney", "classic", "coffee", "coke", "cold", "corn",
    "cottage", "curry", "dal", "dry", "egg", "eggs", "french", "fried",
    "garlic", "ginger", "gravy", "green", "hakka", "half", "honey", "ice",
    "indian", "jeera", "kadai", "kebab", "kurkure", "lachha", "lassi",
    "lemon", "lime", "lollipop", "malaai", "malai", "manchurian", "masala",
    "mayo", "momos", "mushroom", "naan", "noodles", "onion", "oreo", "paan",
    "paneer", "papad", "paratha", "peri", "pepper", "pickle", "pizza",
    "potato", "premium", "raita", "rice", "roll", "rolls", "roti", "salad",
    "sandwich", "shake", "sheek", "seekh", "shahi", "shawarma", "spring",
    "starter", "steamed", "street", "sweet", "tandoor", "tandoori", "tea",
    "thali", "tikka", "tikkas", "tomato", "veg", "vegetable", "vanilla",
    "wings", "wrap", "nuggets", "soup", "soups", "special", "specials",
    "mojito", "juice", "juices", "cooler", "coolers", "mocktail", "papad",
    "mutton", "fish", "prawn", "prawns", "mughlai", "matar", "palak", "korma",
    "kofta", "do", "fried", "garlic", "butter", "cream", "mint", "salt",
    "pepper", "crispy", "boneless", "bone", "full", "double", "jumbo", "mix",
    "fruit", "fresh", "sweet", "hot", "sour", "manchow", "corn", "sweet",
    "szechuan", "schezwan", "chinese", "continental", "mexican", "italian",
}

_STRONG_STARTERS = {
    "paneer", "chicken", "mutton", "egg", "veg", "vegetable", "french", "honey",
    "peri", "cheese", "onion", "masala", "tandoori", "tandoor", "butter", "dal",
    "mushroom", "aloo", "jeera", "chilli", "chili", "garlic", "spring", "chinese",
    "afghani", "steamed", "kurkure", "shawarma", "chicken", "fish", "prawn", "momos",
    "brownie", "oreo", "vanilla", "banana", "apple", "fresh", "green", "fruit",
    "veg", "egg", "rice", "noodles", "burger", "roll", "roti", "naan", "paratha",
}


def _canon_token(token: str) -> str:
    raw = token.casefold()
    if len(raw) < 4 or raw.isdigit():
        return token
    if raw in _MENU_WORDS:
        return token
    best_word = None
    best_score = 0.0
    for word in _MENU_WORDS:
        # Avoid aggressive replacements for very short OCR tokens.
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
    """Repair common OCR corruption without inventing arbitrary item names.

    The local OCR fallback sometimes prefixes an otherwise correct item with
    decorative/menu noise (e.g. ``EE R/ Paneer Tikka``) or makes small word
    substitutions (e.g. ``Chichen Tha``). We correct only against a restaurant
    vocabulary and discard a noisy prefix when a strong food-word starts the
    meaningful suffix.
    """
    value = re.sub(r"\s+", " ", str(value or "")).strip(" .:-|/")
    if not value:
        return value

    raw_tokens = re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)?|\d+|[&+()/.-]", value)
    tokens = [_canon_token(t) for t in raw_tokens]

    # Drop obvious OCR noise before a strong food word. Keep the meaningful
    # suffix rather than trying to hallucinate what the noise meant.
    first_strong = None
    for i, token in enumerate(tokens):
        if token.casefold() in _STRONG_STARTERS:
            first_strong = i
            break
    if first_strong is not None and first_strong > 0:
        prefix = tokens[:first_strong]
        # A prefix containing a real multi-letter menu word is meaningful; a
        # collection of tiny/unknown OCR fragments is usually decoration.
        meaningful_prefix = [t for t in prefix if len(re.sub(r"\W", "", t)) >= 4 and t.casefold() in _MENU_WORDS]
        if not meaningful_prefix:
            tokens = tokens[first_strong:]

    cleaned: list[str] = []
    for token in tokens:
        if token in {"|", "/", ".", ":", "-"}:
            continue
        if len(token) == 1 and not token.isdigit() and token.casefold() not in {"a", "b"}:
            continue
        cleaned.append(token)

    # Normalise casing while retaining common restaurant-style names.
    result = " ".join(cleaned)
    result = re.sub(r"\s*([&+/()])\s*", r" \1 ", result)
    result = re.sub(r"\s+", " ", result).strip()
    return result[:255]


def repair_menu_items(items: list[ImportedMenuItem]) -> list[ImportedMenuItem]:
    repaired: list[ImportedMenuItem] = []
    seen: set[tuple[str, float, str]] = set()

    for item in items:
        name = repair_menu_name(item.name)
        if len(re.sub(r"[^A-Za-z]", "", name)) < 2:
            continue
        category = item.category.strip() if item.category else "Imported Menu"
        key = (name.casefold(), float(item.price), category.casefold())
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
    """Wrap the existing OCR extractor without changing its public API."""
    def wrapped(content: bytes):
        items, warnings = original_extractor(content)
        repaired = repair_menu_items(items)
        if repaired and len(repaired) != len(items):
            warnings = list(warnings) + [
                "OCR name cleanup applied: common OCR typos and decorative prefixes were removed."
            ]
        return repaired, warnings

    return wrapped
