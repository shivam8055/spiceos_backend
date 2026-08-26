from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.menu_import import ImportedMenuItem


def _momo_category(name: str) -> str | None:
    value = name.casefold().replace("–", "-").replace("—", "-")
    if "momo" not in value:
        return None
    if "steamed" in value:
        style = "STEAMED"
    elif "chilli" in value or "chili" in value:
        style = "CHILLI"
    elif "kurkure" in value or "fried" in value:
        style = "KURKURE"
    elif "afghani" in value:
        style = "AFGHANI"
    else:
        style = "OTHER"
    food = "NON-VEG" if any(word in value for word in ("chicken", "mutton", "fish", "prawn", "egg")) else "VEG"
    return f"MOMOS / {style} / {food}"


def enrich_items(items: list[ImportedMenuItem]) -> list[ImportedMenuItem]:
    enriched: list[ImportedMenuItem] = []
    for item in items:
        category = _momo_category(item.name) or item.category.strip() or "Other"
        enriched.append(item.model_copy(update={"category": category}))
    return enriched


def enrich_extractor(original: Callable[..., Awaitable[tuple[list[ImportedMenuItem], list[str]]]]):
    async def wrapped(*args: Any, **kwargs: Any):
        items, warnings = await original(*args, **kwargs)
        return enrich_items(items), list(warnings) + [
            "Menu categories normalized: Momo variants are separated by preparation style and Veg/Non-Veg so they can be filtered and ordered easily."
        ]

    return wrapped
