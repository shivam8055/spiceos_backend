import asyncio
import base64
import hashlib
import io
import json
import os
import re
import time

import httpx
import pytesseract
from PIL import Image, ImageOps
from pytesseract import Output

from app.schemas.menu_import import ImportedMenuItem


class MenuImportError(RuntimeError):
    pass


# Small process-local cache prevents repeated clicks/retries from sending the
# exact same image to OpenAI over and over while a user is testing an import.
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
    """Respect OpenAI's Retry-After header without blocking the service too long."""
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return min(max(float(retry_after), 1.0), 15.0)
        except ValueError:
            pass
    return 3.0


async def _openai_extract(payload: dict, api_key: str, model: str) -> httpx.Response:
    """Make one request; on 429, wait for Retry-After and make one clean retry."""
    request_payload = {**payload, "model": model}
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
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
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
        )


def _prepare_menu_image(content: bytes, content_type: str) -> tuple[bytes, str]:
    """Normalize phone/WhatsApp images before sending to vision or OCR."""
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")

        max_dimension = 1800
        if max(image.size) > max_dimension:
            scale = max_dimension / max(image.size)
            image = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.LANCZOS,
            )

        output = io.BytesIO()
        image.save(output, format="JPEG", quality=78, optimize=True)
        prepared = output.getvalue()
        if len(prepared) <= 4 * 1024 * 1024:
            return prepared, "image/jpeg"
    except Exception:
        pass
    return content, content_type


def _parse_result(response: httpx.Response) -> tuple[list[ImportedMenuItem], list[str]]:
    try:
        text = response.json()["choices"][0]["message"]["content"]
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        data = json.loads(text)
        items = [ImportedMenuItem.model_validate(item) for item in data.get("items", [])]
        warnings = [str(w) for w in data.get("warnings", [])]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MenuImportError("AI returned an unreadable menu. Please try a clearer image.") from exc
    return items, warnings


def _clean_ocr_line(value: str) -> str:
    value = re.sub(r"[\u2022\u25cf\u25aa\u2013\u2014]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .:-|\t")
    return value


def _parse_price_line(line: str) -> tuple[str, float] | None:
    """Extract a menu item and its trailing price from common Indian menu formats."""
    line = _clean_ocr_line(line)
    if not line:
        return None

    # OCR frequently turns ₹ into ?, R, or Rs. Accept those forms but only
    # when a 2-5 digit price is at the end of the line.
    match = re.search(r"(?:₹|Rs\.?|INR|\?)?\s*(\d{2,5}(?:[.,]\d{1,2})?)\s*$", line, re.I)
    if not match:
        return None

    raw_price = match.group(1).replace(",", "")
    try:
        price = float(raw_price)
    except ValueError:
        return None

    # Avoid treating years/phone numbers as prices.
    if price < 10 or price > 100000:
        return None

    name = line[: match.start()].strip(" .:-|\t₹?RrsIN")
    name = re.sub(r"\s+", " ", name).strip(" .:-|\t")
    if len(name) < 2:
        return None
    return name[:255], price


def _looks_like_category(line: str) -> bool:
    line = _clean_ocr_line(line)
    if not line or len(line) > 55 or re.search(r"\d", line):
        return False
    words = line.split()
    if len(words) > 7:
        return False
    # Headings are commonly uppercase, title-cased, or short labels.
    letters = [c for c in line if c.isalpha()]
    upper_ratio = sum(c.isupper() for c in letters) / max(1, len(letters))
    return upper_ratio > 0.65 or len(words) <= 4


def _local_ocr_extract(content: bytes) -> tuple[list[ImportedMenuItem], list[str]]:
    """Offline fallback used when OpenAI has no quota or is temporarily unavailable."""
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image).convert("RGB")
        if max(image.size) < 1400:
            scale = 1400 / max(image.size)
            image = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.LANCZOS,
            )

        # psm 6 works well for photographed menus containing multiple columns.
        text = pytesseract.image_to_string(image, lang="eng+hin", config="--psm 6")
    except Exception as exc:
        raise MenuImportError(
            "AI credits are unavailable and the local OCR fallback could not run. "
            "Please add OpenAI credits or upload a clearer menu image."
        ) from exc

    items: list[ImportedMenuItem] = []
    warnings: list[str] = []
    current_category = "Imported Menu"
    seen: set[tuple[str, float]] = set()

    for raw_line in text.splitlines():
        line = _clean_ocr_line(raw_line)
        if not line:
            continue

        parsed = _parse_price_line(line)
        if parsed:
            name, price = parsed
            # Remove obvious OCR artefacts and extremely long descriptions.
            name = re.sub(r"\s{2,}", " ", name).strip()
            if not name or name.lower() in {"menu", "price", "items"}:
                continue
            key = (name.casefold(), price)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                ImportedMenuItem(
                    category=current_category[:100],
                    name=name,
                    description=None,
                    price=price,
                    available=True,
                )
            )
        elif _looks_like_category(line):
            current_category = line[:100]

    if not items:
        warnings.append(
            "Local OCR could not confidently find item prices. Try a sharper, straight-on menu photo."
        )
    else:
        warnings.append(
            "Imported with local OCR because OpenAI credits/rate limits were unavailable. Review item names and prices before publishing."
        )

    return items, warnings


async def extract_menu_from_image(content: bytes, content_type: str) -> tuple[list[ImportedMenuItem], list[str]]:
    api_key = os.getenv("OPENAI_API_KEY")

    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise MenuImportError("Please upload a JPG, PNG, or WEBP menu image.")
    if len(content) > 15 * 1024 * 1024:
        raise MenuImportError("Menu image is too large. Maximum size is 15 MB.")

    prepared_content, prepared_type = _prepare_menu_image(content, content_type)

    # If no OpenAI key is configured, do not make the feature unusable: use
    # the local OCR fallback instead.
    if not api_key:
        return _local_ocr_extract(prepared_content)

    configured_primary = os.getenv("OPENAI_MENU_MODEL", "gpt-4o-mini").strip()
    configured_fallback = os.getenv("OPENAI_MENU_FALLBACK_MODEL", "gpt-4.1-mini").strip()

    models: list[str] = []
    for model in ("gpt-4o-mini", configured_primary, configured_fallback, "gpt-4.1-mini"):
        if model and model not in models:
            models.append(model)

    detail = os.getenv("OPENAI_MENU_IMAGE_DETAIL", "low").strip().lower()
    if detail not in {"low", "high", "auto"}:
        detail = "low"

    image_data = base64.b64encode(prepared_content).decode("ascii")
    prompt = """Read this restaurant menu and return ONLY valid JSON in this exact shape: {\"items\":[{\"category\":\"...\",\"name\":\"...\",\"description\":null,\"price\":123.0,\"available\":true}],\"warnings\":[\"...\"]}. Preserve visible item names and prices. Never invent a price. If a price is unreadable, omit that item and add a warning. Remove currency symbols from numeric prices. Infer categories only when clearly shown. Keep descriptions short."""

    payload = {
        "temperature": 0,
        "max_tokens": 650,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{prepared_type};base64,{image_data}", "detail": detail}},
            ],
        }],
    }

    response: httpx.Response | None = None
    last_code: str | None = None
    last_message: str | None = None

    for index, model in enumerate(models[:2]):
        cache_key = _cache_key(prepared_content, model)
        cached = _CACHE.get(cache_key)
        if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1], cached[2]
        if cached:
            _CACHE.pop(cache_key, None)

        response = await _openai_extract(payload, api_key, model)
        if response.status_code < 400:
            items, warnings = _parse_result(response)
            _CACHE[cache_key] = (time.time(), items, warnings)
            return items, warnings

        last_code, last_message = _read_openai_error(response)
        if response.status_code != 429:
            break
        if last_code == "insufficient_quota":
            break
        if index == 0 and len(models) > 1:
            continue

    # Critical reliability path: an OpenAI quota/rate-limit must no longer
    # make menu import unusable. Fall back to local OCR before returning 429.
    if response is not None and response.status_code == 429:
        try:
            return _local_ocr_extract(prepared_content)
        except MenuImportError:
            if last_code == "insufficient_quota":
                raise MenuImportError(
                    "OpenAI API quota is exhausted and local OCR could not extract this menu. "
                    "Add API credits to the OpenAI project used by OPENAI_API_KEY or upload a clearer image."
                )
            detail_text = last_message or "OpenAI is temporarily rate-limiting the menu import request"
            raise MenuImportError(
                f"{detail_text}. Local OCR was also unavailable; please try again with a clearer image."
            )

    if response is None:
        return _local_ocr_extract(prepared_content)
    if last_message:
        raise MenuImportError(f"OpenAI menu extraction failed: {last_message}")
    raise MenuImportError(f"AI menu extraction failed ({response.status_code}).")
