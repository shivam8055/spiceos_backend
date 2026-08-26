import asyncio
import base64
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import time

import httpx
import pytesseract
from PIL import Image, ImageEnhance, ImageOps

from app.schemas.menu_import import ImportedMenuItem


class MenuImportError(RuntimeError):
    pass


class OpenAIRateLimitError(RuntimeError):
    def __init__(self, response: httpx.Response):
        self.response = response
        super().__init__("OpenAI rate limit")


_CACHE: dict[str, tuple[float, list[ImportedMenuItem], list[str]]] = {}
_CACHE_TTL_SECONDS = 10 * 60


def _cache_key(content: bytes, model: str) -> str:
    return hashlib.sha256(model.encode("utf-8") + b"\0" + content).hexdigest()


def _read_openai_error(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        error = response.json().get("error", {})
        return error.get("code"), error.get("message")
    except (ValueError, TypeError, AttributeError):
        return None, None


def _retry_delay(response: httpx.Response) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return min(max(float(retry_after), 1.0), 15.0)
        except ValueError:
            pass
    return 3.0


async def _openai_extract(payload: dict, api_key: str, model: str) -> httpx.Response:
    request_payload = {**payload, "model": model}
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=request_payload,
        )
        if response.status_code != 429:
            return response
        code, _ = _read_openai_error(response)
        if code == "insufficient_quota":
            return response
        await asyncio.sleep(_retry_delay(response))
        return await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=request_payload,
        )


def _prepare_menu_image(content: bytes, content_type: str) -> tuple[bytes, str]:
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        max_dimension = 3000
        if max(image.size) > max_dimension:
            scale = max_dimension / max(image.size)
            image = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.LANCZOS,
            )
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
        prepared = output.getvalue()
        if len(prepared) <= 8 * 1024 * 1024:
            return prepared, "image/jpeg"
    except Exception:
        pass
    return content, content_type


def _parse_result(response: httpx.Response) -> tuple[list[ImportedMenuItem], list[str]]:
    try:
        text = response.json()["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in text)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text).strip())
        data = json.loads(text)
        items = [ImportedMenuItem.model_validate(item) for item in data.get("items", [])]
        warnings = [str(w) for w in data.get("warnings", [])]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MenuImportError("AI returned an unreadable menu. Please try a clearer image.") from exc
    return items, warnings


def _clean_ocr_line(value: str) -> str:
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[\u2022\u25cf\u25aa\u2013\u2014]+", " ", value)
    value = re.sub(r"[|]{2,}", " ", value)
    return re.sub(r"\s+", " ", value).strip(" .:-|\t")


def _normalise_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9&'()/%+ .-]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .:-")
    return value[:255]


def _parse_price_line(line: str) -> tuple[str, float] | None:
    line = _clean_ocr_line(line)
    if not line:
        return None
    match = re.search(r"(?:₹|Rs\.?|INR|\?)?\s*(\d{2,4}(?:[.,]\d{1,2})?)\s*$", line, re.I)
    if not match:
        return None
    try:
        price = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    if price < 10 or price > 5000:
        return None
    name = _normalise_name(line[:match.start()])
    name = re.sub(r"\b(?:Rs|INR|Rrs|Rss)$", "", name, flags=re.I).strip()
    letters = sum(c.isalpha() for c in name)
    if len(name) < 2 or letters < 2 or letters / max(1, len(name)) < 0.45:
        return None
    return name, price


def _looks_like_category(line: str) -> bool:
    """Only treat heading-like OCR lines as categories.

    The previous implementation classified every short line as a category,
    which caused normal item names such as Green Salad to become categories.
    """
    line = _clean_ocr_line(line)
    if not line or len(line) > 60 or re.search(r"\d", line):
        return False
    words = line.split()
    if len(words) > 7:
        return False
    letters = [c for c in line if c.isalpha()]
    if len(letters) < 3:
        return False
    upper_ratio = sum(c.isupper() for c in letters) / len(letters)
    return upper_ratio >= 0.78


def _ocr_language() -> str:
    if not shutil.which("tesseract"):
        raise MenuImportError(
            "Local OCR engine is not installed on the backend. The deployment must include Tesseract OCR."
        )
    try:
        installed = set(pytesseract.get_languages(config=""))
    except Exception as exc:
        raise MenuImportError("Local OCR engine is installed but could not be initialized.") from exc
    if "eng" in installed and "hin" in installed:
        return "eng+hin"
    if "eng" in installed:
        return "eng"
    if installed:
        return sorted(installed)[0]
    raise MenuImportError("Tesseract is installed but no OCR language data is available.")


def _menu_regions(image: Image.Image) -> list[Image.Image]:
    """Split dense portrait menus into overlapping vertical regions."""
    w, h = image.size
    if w < 900 or w / max(1, h) > 0.9:
        return [image]
    overlap = max(20, round(w * 0.035))
    cuts = [0, round(w / 3), round(2 * w / 3), w]
    return [
        image.crop((
            max(0, cuts[i] - (overlap if i else 0)),
            0,
            min(w, cuts[i + 1] + (overlap if i < 2 else 0)),
            h,
        ))
        for i in range(3)
    ]


def _cluster_candidates(candidates: list[tuple[str, float, int]]) -> list[tuple[str, float]]:
    """Merge OCR variants by fuzzy item name and vote on their prices."""
    clusters: list[dict] = []
    for name, price, weight in candidates:
        key = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
        best = None
        best_score = 0.0
        for cluster in clusters:
            score = difflib.SequenceMatcher(None, key, cluster["key"]).ratio()
            if score > best_score:
                best_score = score
                best = cluster
        if best is None or best_score < 0.78:
            clusters.append({"key": key, "names": [(name, weight)], "prices": [(price, weight)]})
        else:
            best["names"].append((name, weight))
            best["prices"].append((price, weight))
            best["key"] = max(best["key"], key, key=len)

    result = []
    for cluster in clusters:
        name = max(cluster["names"], key=lambda x: (x[1], len(x[0])))[0]
        price_scores: dict[float, int] = {}
        for price, weight in cluster["prices"]:
            price_scores[price] = price_scores.get(price, 0) + weight
        price = sorted(price_scores.items(), key=lambda x: (-x[1], x[0]))[0][0]
        result.append((name, price))
    return result


def _clean_price_ocr(raw: str) -> float | None:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    # Tesseract often reads the rupee glyph as a leading digit:
    # 59 -> 259, 109 -> 7109, 139 -> 7139, 249 -> 2249.
    if len(digits) == 4 and digits[0] in {"2", "3", "7", "8", "9"}:
        tail = digits[1:]
        if 10 <= int(tail) <= 999:
            digits = tail
    value = float(digits)
    if value < 10 or value > 5000:
        return None
    return value


def _ocr_price_from_token(image: Image.Image, x: int, y: int, w: int, h: int) -> float | None:
    pad = max(3, round(max(w, h) * 0.18))
    crop = image.crop((
        max(0, x - pad), max(0, y - pad),
        min(image.width, x + w + pad), min(image.height, y + h + pad),
    ))
    crop = crop.resize((max(30, crop.width * 5), max(20, crop.height * 5)), Image.Resampling.LANCZOS)
    try:
        raw = pytesseract.image_to_string(
            crop, config="--psm 7 -c tessedit_char_whitelist=0123456789"
        )
    except Exception:
        return None
    return _clean_price_ocr(raw)


def _local_ocr_extract(content: bytes) -> tuple[list[ImportedMenuItem], list[str]]:
    """Deterministic offline fallback for OpenAI quota/rate-limit failures.

    Tesseract word boxes are used so the price is re-read from the actual
    printed price token instead of trusting OCR's interpretation of the rupee
    glyph. Columns are processed independently so unrelated menu sections do
    not get merged.
    """
    language = _ocr_language()
    try:
        source = Image.open(io.BytesIO(content))
        source = ImageOps.exif_transpose(source).convert("RGB")
        if max(source.size) < 1800:
            scale = 1800 / max(source.size)
            source = source.resize(
                (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
                Image.Resampling.LANCZOS,
            )

        gray = ImageOps.autocontrast(ImageOps.grayscale(source))
        contrast = ImageEnhance.Contrast(gray).enhance(1.45)
        threshold = contrast.point(lambda p: 255 if p > 105 else 0)
        variants: list[tuple[Image.Image, int]] = [(threshold, 4), (contrast, 2)]
        candidates_by_category: dict[str, list[tuple[str, float, int]]] = {}

        for variant, variant_weight in variants:
            for region in _menu_regions(variant):
                current_category = "Imported Menu"
                try:
                    data = pytesseract.image_to_data(
                        region,
                        lang=language,
                        config="--psm 4",
                        output_type=pytesseract.Output.DICT,
                    )
                except Exception:
                    continue

                lines: dict[tuple[int, int, int], list[int]] = {}
                for i, raw in enumerate(data["text"]):
                    if not str(raw).strip():
                        continue
                    key = (
                        int(data["block_num"][i]),
                        int(data["par_num"][i]),
                        int(data["line_num"][i]),
                    )
                    lines.setdefault(key, []).append(i)

                for indices in lines.values():
                    indices.sort(key=lambda i: data["left"][i])
                    words = [str(data["text"][i]).strip() for i in indices if str(data["text"][i]).strip()]
                    line = _clean_ocr_line(" ".join(words))
                    if not line:
                        continue

                    numeric_indices = [
                        i for i in indices if re.search(r"\d", str(data["text"][i]))
                    ]
                    if numeric_indices:
                        price_token = numeric_indices[-1]
                        x = int(data["left"][price_token])
                        y = int(data["top"][price_token])
                        w = int(data["width"][price_token])
                        h = int(data["height"][price_token])
                        price = _ocr_price_from_token(region, x, y, w, h)
                        if price is None:
                            price = _clean_price_ocr(str(data["text"][price_token]))
                        if price is not None:
                            name_parts = [
                                str(data["text"][i]).strip()
                                for i in indices
                                if i != price_token and not re.search(r"\d", str(data["text"][i]))
                            ]
                            name = _normalise_name(" ".join(name_parts))
                            letters = sum(c.isalpha() for c in name)
                            if len(name) >= 2 and letters >= 2 and letters / max(1, len(name)) >= 0.45:
                                candidates_by_category.setdefault(current_category, []).append(
                                    (name, price, variant_weight)
                                )
                                continue

                    if _looks_like_category(line):
                        current_category = _normalise_name(line) or current_category

        items: list[ImportedMenuItem] = []
        seen: set[tuple[str, float]] = set()
        for category, candidates in candidates_by_category.items():
            for name, price in _cluster_candidates(candidates):
                key = (name.casefold(), price)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    ImportedMenuItem(
                        category=category,
                        name=name,
                        description=None,
                        price=price,
                        available=True,
                    )
                )
    except MenuImportError:
        raise
    except Exception as exc:
        raise MenuImportError(
            "Local OCR could not process this menu image. Please upload a clearer image."
        ) from exc

    warnings: list[str] = []
    if not items:
        warnings.append(
            "Local OCR ran successfully but could not confidently find item prices. Try a sharp, straight-on menu photo."
        )
    else:
        warnings.append(
            "Imported with local OCR because OpenAI credits/rate limits were unavailable. Review the preview before publishing; table-style sections may need manual review."
        )
    return items, warnings


async def _openai_extract_regions(
    prepared_content: bytes,
    prepared_type: str,
    api_key: str,
    model: str,
    detail: str,
) -> tuple[list[ImportedMenuItem], list[str]]:
    """Extract each menu column separately, then merge."""
    image = Image.open(io.BytesIO(prepared_content))
    image = ImageOps.exif_transpose(image).convert("RGB")
    regions = _menu_regions(image)

    prompt = """Extract ONLY the food/drink items and their visible prices from this menu region.
Return valid JSON exactly:
{"items":[{"category":"CATEGORY","name":"ITEM NAME","description":null,"price":123.0,"available":true}],"warnings":[]}

Rules:
- Copy item names exactly as visible; do not paraphrase.
- Copy the numeric price exactly. NEVER guess, calculate, or invent a price.
- Ignore phone numbers, WhatsApp numbers, dates, slogans, delivery text, and decorative text.
- Ignore photos and illustrations.
- If a section has a table (for example multiple momo variants), extract each row/variant only when the row label and price are clearly readable.
- Use the nearest clearly printed section heading as category.
- Do not merge two different items.
- Do not put several items into one name.
- Descriptions must be null unless a description is clearly printed separately.
- If a price or item name is unclear, omit that item and add a short warning.
"""

    all_items: list[ImportedMenuItem] = []
    warnings: list[str] = []
    for region in regions:
        output = io.BytesIO()
        region.save(output, format="JPEG", quality=92, optimize=True)
        data = base64.b64encode(output.getvalue()).decode("ascii")
        payload = {
            "temperature": 0,
            "max_tokens": 2200,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{data}",
                    "detail": detail,
                }},
            ]}],
        }
        response = await _openai_extract(payload, api_key, model)
        if response.status_code >= 400:
            code, message = _read_openai_error(response)
            if response.status_code == 429:
                raise OpenAIRateLimitError(response)
            raise MenuImportError(message or f"OpenAI menu extraction failed ({response.status_code}).")
        items, region_warnings = _parse_result(response)
        all_items.extend(items)
        warnings.extend(region_warnings)

    deduped: list[ImportedMenuItem] = []
    seen: set[tuple[str, str, float]] = set()
    for item in all_items:
        name = _normalise_name(item.name)
        category = _normalise_name(item.category) or "Imported Menu"
        key = (category.casefold(), name.casefold(), float(item.price))
        if not name or key in seen:
            continue
        seen.add(key)
        deduped.append(
            ImportedMenuItem(
                category=category,
                name=name,
                description=item.description,
                price=item.price,
                available=item.available,
            )
        )
    return deduped, warnings


async def extract_menu_from_image(content: bytes, content_type: str) -> tuple[list[ImportedMenuItem], list[str]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise MenuImportError("Please upload a JPG, PNG, or WEBP menu image.")
    if len(content) > 15 * 1024 * 1024:
        raise MenuImportError("Menu image is too large. Maximum size is 15 MB.")

    prepared_content, prepared_type = _prepare_menu_image(content, content_type)
    if not api_key:
        return _local_ocr_extract(prepared_content)

    configured_primary = os.getenv("OPENAI_MENU_MODEL", "gpt-4.1-mini").strip()
    configured_fallback = os.getenv("OPENAI_MENU_FALLBACK_MODEL", "gpt-4o-mini").strip()
    models: list[str] = []
    for model in (configured_primary, configured_fallback, "gpt-4.1-mini", "gpt-4o-mini"):
        if model and model not in models:
            models.append(model)

    detail = os.getenv("OPENAI_MENU_IMAGE_DETAIL", "high").strip().lower()
    if detail not in {"low", "high", "auto"}:
        detail = "high"

    last_code: str | None = None
    last_message: str | None = None

    for model in models[:2]:
        cache_key = _cache_key(prepared_content, model)
        cached = _CACHE.get(cache_key)
        if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1], cached[2]
        if cached:
            _CACHE.pop(cache_key, None)

        try:
            items, warnings = await _openai_extract_regions(
                prepared_content, prepared_type, api_key, model, detail
            )
            if not items:
                raise MenuImportError("AI could not confidently read any menu items.")
            _CACHE[cache_key] = (time.time(), items, warnings)
            return items, warnings
        except OpenAIRateLimitError as exc:
            response = exc.response
            last_code, last_message = _read_openai_error(response)
            if last_code == "insufficient_quota":
                break
            continue
        except MenuImportError as exc:
            last_message = str(exc)
            break

    try:
        return _local_ocr_extract(prepared_content)
    except MenuImportError as exc:
        if last_code == "insufficient_quota":
            raise MenuImportError(
                "OpenAI credits are exhausted and the local OCR fallback is unavailable. The backend deployment must include Tesseract OCR."
            ) from exc
        if last_message:
            raise MenuImportError(f"{last_message}. Local OCR fallback is unavailable.") from exc
        raise
