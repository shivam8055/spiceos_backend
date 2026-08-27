import re
from collections.abc import Callable
from typing import Any

from app.schemas.menu_import import ImportedMenuItem


def _normalise_text(value: str) -> str:
    value = str(value or "").replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value).strip(" .:-|\t")
    return value[:255]


def repair_menu_items(items: list[ImportedMenuItem]) -> list[ImportedMenuItem]:
    """Clean OCR names without using the restaurant catalog as a hard filter.

    Every reasonably structured OCR item is retained as a reviewable draft.
    Catalog matching belongs in deduplication/enrichment, not extraction.
    """
    repaired: list[ImportedMenuItem] = []
    seen: set[tuple[str, float, str]] = set()

    for item in items:
        name = _normalise_text(item.name)
        category = _normalise_text(item.category) or "Imported Menu"
        try:
            price = float(item.price)
        except (TypeError, ValueError):
            continue

        if len(re.sub(r"[^A-Za-z0-9]", "", name)) < 2 or price < 0:
            continue

        key = (name.casefold(), price, category.casefold())
        if key in seen:
            continue
        seen.add(key)
        repaired.append(
            item.model_copy(
                update={
                    "category": category,
                    "name": name,
                    "price": price,
                }
            )
        )

    return repaired


def repair_local_ocr(original_extractor: Callable[..., tuple[list[ImportedMenuItem], list[str]]]):
    """Preserve unmatched OCR items as reviewable drafts.

    The previous Spice Box-specific repair pass discarded every OCR item that
    failed to match the canonical Spice Box catalog. That made valid restaurant
    menu items disappear during import. This wrapper deliberately keeps them.
    """
    def wrapped(content: bytes, *args: Any, **kwargs: Any):
        items, warnings = original_extractor(content, *args, **kwargs)
        repaired = repair_menu_items(items)
        warnings = list(warnings)
        if len(repaired) != len(items):
            warnings.append(
                f"{len(items) - len(repaired)} OCR entries were removed because they were empty, invalid, or duplicated."
            )
        warnings.append(
            "Catalog matching is no longer a hard filter: unmatched menu items are retained as drafts for manual review."
        )
        return repaired, warnings

    return wrapped
