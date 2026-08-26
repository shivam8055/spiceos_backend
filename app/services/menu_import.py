import asyncio
import base64
import hashlib
import io
import json
import os
import re
import time

import httpx
from PIL import Image, ImageOps

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
    """Normalize phone/WhatsApp images before sending them to vision."""
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")

        max_dimension = 1400
        if max(image.size) > max_dimension:
            scale = max_dimension / max(image.size)
            image = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.LANCZOS,
            )

        output = io.BytesIO()
        image.save(output, format="JPEG", quality=70, optimize=True)
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


async def extract_menu_from_image(content: bytes, content_type: str) -> tuple[list[ImportedMenuItem], list[str]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise MenuImportError("AI menu import is not configured. Set OPENAI_API_KEY on the backend.")

    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise MenuImportError("Please upload a JPG, PNG, or WEBP menu image.")
    if len(content) > 15 * 1024 * 1024:
        raise MenuImportError("Menu image is too large. Maximum size is 15 MB.")

    prepared_content, prepared_type = _prepare_menu_image(content, content_type)
    configured_primary = os.getenv("OPENAI_MENU_MODEL", "gpt-4o-mini").strip()
    configured_fallback = os.getenv("OPENAI_MENU_FALLBACK_MODEL", "gpt-4o-mini").strip()

    # Prefer the configured model, but never burn the user's rate limit by
    # trying several models repeatedly. One primary request + one fallback.
    models: list[str] = []
    for model in (configured_primary, configured_fallback, "gpt-4o-mini", "gpt-4.1-mini"):
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
        # If the primary is rate-limited, use the fallback once. The fallback
        # is deliberately not retried again, avoiding a rate-limit storm.
        if index == 0 and len(models) > 1:
            continue

    if response is None:
        raise MenuImportError("AI menu extraction did not start.")

    if response.status_code == 429 and last_code == "insufficient_quota":
        raise MenuImportError("OpenAI API quota is exhausted. Add API credits/billing to the OpenAI project used by OPENAI_API_KEY, then try again.")
    if response.status_code == 429:
        detail_text = last_message or "OpenAI is temporarily rate-limiting the menu import request"
        raise MenuImportError(f"OpenAI menu extraction is temporarily rate-limited. Please wait 15–30 seconds and try again. {detail_text}")
    if last_message:
        raise MenuImportError(f"OpenAI menu extraction failed: {last_message}")
    raise MenuImportError(f"AI menu extraction failed ({response.status_code}).")
