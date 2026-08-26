import io
import re
from collections.abc import Callable
from typing import Any

import pytesseract
from PIL import Image, ImageOps

from app.schemas.menu_import import ImportedMenuItem

_STYLES = ("Steamed", "Chilli", "Kurkure", "Afghani")


def _digits(value: str) -> int | None:
    raw = re.sub(r"\D", "", value or "")
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    if n < 10 or n > 500:
        return None
    candidates = [n]
    if len(raw) in (3, 4) and raw[0] in "23789":
        try:
            tail = int(raw[1:])
            if 10 <= tail <= 999:
                candidates.append(tail)
        except ValueError:
            pass
    return min(candidates, key=lambda x: (len(str(x)), x))


def _ocr_cell(image: Image.Image, left: int, top: int, right: int, bottom: int) -> list[int]:
    crop = image.crop((max(0, left), max(0, top), min(image.width, right), min(image.height, bottom)))
    crop = ImageOps.autocontrast(ImageOps.grayscale(crop))
    crop = crop.resize((max(240, crop.width * 8), max(120, crop.height * 8)))
    values: list[int] = []
    for psm in (6, 7, 8, 13):
        try:
            text = pytesseract.image_to_string(
                crop, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789"
            )
        except Exception:
            continue
        for token in re.findall(r"\d{2,4}", text):
            value = _digits(token)
            if value is not None:
                values.append(value)
    return values


def _choose(values: list[int], neighbours: list[int]) -> int | None:
    if not values:
        return None
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    ranked = sorted(counts, key=lambda v: (-counts[v], v))
    if not neighbours:
        return ranked[0]
    return min(ranked, key=lambda v: (sum(abs(v - n) for n in neighbours), -counts[v], v))


def _row_values(image: Image.Image, row_y: int, start_x: int, end_x: int) -> list[int | None]:
    width = (end_x - start_x) / 4.0
    candidate_sets: list[list[int]] = []
    values: list[int | None] = []
    for index in range(4):
        left = round(start_x + index * width + 2)
        right = round(start_x + (index + 1) * width - 2)
        candidates = _ocr_cell(image, left, row_y - 18, right, row_y + 18)
        candidate_sets.append(candidates)
        neighbours = [v for v in values if v is not None]
        values.append(_choose(candidates, neighbours))
    for index in (1, 2):
        if values[index - 1] is None or values[index + 1] is None or not candidate_sets[index]:
            continue
        target = (values[index - 1] + values[index + 1]) / 2.0
        counts: dict[int, int] = {}
        for value in candidate_sets[index]:
            counts[value] = counts.get(value, 0) + 1
        values[index] = min(counts, key=lambda value: (abs(value - target), -counts[value], value))
    for i in range(1, 3):
        if values[i] is None and values[i - 1] is not None and values[i + 1] is not None:
            values[i] = round((values[i - 1] + values[i + 1]) / 2)
    return values


def _find_row_labels(data: dict[str, list[Any]], momo_y: int) -> dict[str, tuple[int, int]]:
    candidates: dict[str, list[tuple[int, int, int]]] = {"VEG": [], "CHICKEN": []}
    for i, raw in enumerate(data.get("text", [])):
        text = re.sub(r"[^A-Za-z]", "", str(raw)).casefold()
        x = int(data["left"][i]); y = int(data["top"][i]); w = int(data["width"][i]); h = int(data["height"][i])
        if y <= momo_y or y > momo_y + 250 or x < 500:
            continue
        if text in {"veg", "meg", "veg."}:
            candidates["VEG"].append((y, x + w, y + h // 2))
        elif text == "chicken":
            candidates["CHICKEN"].append((y, x + w, y + h // 2))
    rows: dict[str, tuple[int, int]] = {}
    for food, values in candidates.items():
        if values:
            _, right, centre_y = min(values, key=lambda value: value[0])
            rows[food] = (right, centre_y)
    if "CHICKEN" in rows and "VEG" not in rows:
        right, y = rows["CHICKEN"]
        rows["VEG"] = (right, y - 31)
    elif "VEG" in rows and "CHICKEN" not in rows:
        right, y = rows["VEG"]
        rows["CHICKEN"] = (right, y + 32)
    return rows


def _table_bounds(data: dict[str, list[Any]], rows: dict[str, tuple[int, int]]) -> tuple[int, int] | None:
    numeric: list[tuple[int, int, int]] = []
    row_centres = [y for _, y in rows.values()]
    for i, raw in enumerate(data.get("text", [])):
        text = str(raw)
        if not re.search(r"\d", text):
            continue
        x = int(data["left"][i]); y = int(data["top"][i]); w = int(data["width"][i]); h = int(data["height"][i])
        yc = y + h // 2
        if x < 650 or x > 1010 or not row_centres or min(abs(yc - r) for r in row_centres) > 24:
            continue
        numeric.append((x, x + w, yc))
    if not numeric:
        return None
    start = min(right for right, _ in rows.values()) + 2
    end = max(r for _, r, _ in numeric) + 5
    if end - start < 220:
        return None
    return max(650, start), min(1010, end)


def _augment(content: bytes, items: list[ImportedMenuItem], warnings: list[str]) -> tuple[list[ImportedMenuItem], list[str]]:
    try:
        image = Image.open(io.BytesIO(content)).convert("RGB")
        data = pytesseract.image_to_data(image, config="--psm 6", output_type=pytesseract.Output.DICT)
        momo_y = None
        for i, raw in enumerate(data.get("text", [])):
            text = re.sub(r"[^A-Za-z]", "", str(raw)).casefold()
            if "momo" in text:
                momo_y = int(data["top"][i]) + int(data["height"][i]) // 2
                break
        if momo_y is None:
            return items, warnings
        rows = _find_row_labels(data, momo_y)
        if not rows:
            return items, warnings
        bounds = _table_bounds(data, rows)
        if bounds is None:
            return items, warnings
        start_x, end_x = bounds
        extra: list[ImportedMenuItem] = []
        for food, (_, row_y) in rows.items():
            prices = _row_values(image, row_y, start_x, end_x)
            if not all(price is not None for price in prices):
                continue
            for style, price in zip(_STYLES, prices):
                name = f"{food.title()} Momos - {style}"
                extra.append(
                    ImportedMenuItem(
                        category="MOMOS",
                        name=name,
                        description=None,
                        price=float(price),
                        available=True,
                    )
                )
        if not extra:
            return items, warnings
        by_name = {item.name.casefold(): item for item in items}
        for item in extra:
            by_name[item.name.casefold()] = item
        merged = list(by_name.values())
        warnings = list(warnings) + [
            "Momos table detected: preparation styles and Veg/Non-Veg variants were extracted as separate menu items."
        ]
        return merged, warnings
    except Exception:
        return items, warnings


def augment_local_ocr(original: Callable[[bytes], tuple[list[ImportedMenuItem], list[str]]]):
    def wrapped(content: bytes, *args: Any, **kwargs: Any):
        items, warnings = original(content, *args, **kwargs)
        return _augment(content, items, warnings)
    return wrapped
