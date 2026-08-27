from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.menu_import import ImportedMenuItem


def _momo_category(name: str) -> str | None:
    value = name.casefold().replace("–", "-").replace("—", "-")
    if "momo" not in value:
        return None
    # Keep all momo variants under one parent category. Preparation style and
    # Veg/Non-Veg remain in the item name so the import review screen shows the
    # complete momo section instead of scattering it into one-item categories.
    return "MOMOS"


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
            "Menu categories normalized: all Momo variants are grouped under MOMOS while preparation style and Veg/Non-Veg remain visible in item names."
        ]

    return wrapped
