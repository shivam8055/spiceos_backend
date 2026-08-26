import asyncio
import base64
import io
import json
import os
import re

import httpx
from PIL import Image, ImageOps

from app.schemas.menu_import import ImportedMenuItem


class MenuImportError(RuntimeError):
    pass


async def _openai_extract(payload: dict, api_key: str) -> httpx.Response:
    """Call OpenAI with one short retry; model fallback handles persistent 429s."""
    async with httpx.AsyncClient(timeout=90) as client:
        for attempt in range(2):
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code != 429 or attempt == 1:
                return response

            try:
                error = response.json().get("error", {})
                if error.get("code") == "insufficient_quota":
                    return response
            except (ValueError, TypeError):
                pass

            retry_after = response.headers.get("retry-after")
            try:
                delay = min(float(retry_after), 8.0) if retry_after else 2.0
            except ValueError:
                delay = 2.0
            await asyncio.sleep(delay)

    raise RuntimeError("OpenAI request failed unexpectedly.")


async def _extract_with_model(payload: dict, api_key: str, model: str) -> httpx.Response:
    payload = {**payload, "model": model}
    return await _openai_extract(payload, api_key)


def _prepare_menu_image(content: bytes, content_type: str) -> tuple[bytes, str]:
    """Normalize large phone/WhatsApp images before sending them to vision."""
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")

        max_dimension = 1600
        if max(image.size) > max_dimension:
            scale = max_dimension / max(image.size)
            image = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.LANCZOS,
            )

        output = io.BytesIO()
        image.save(output, format="JPEG", quality=72, optimize=True)
        prepared = output.getvalue()
        if len(prepared) <= 4 * 1024 * 1024:
            return prepared, "image/jpeg"
    except Exception:
        pass
    return content, content_type


async def extract_menu_from_image(content: bytes, content_type: str) -> tuple[list[ImportedMenuItem], list[str]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise MenuImportError("AI menu import is not configured. Set OPENAI_API_KEY on the backend.")

    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise MenuImportError("Please upload a JPG, PNG, or WEBP menu image.")
    if len(content) > 15 * 1024 * 1024:
        raise MenuImportError("Menu image is too large. Maximum size is 15 MB.")

    prepared_content, prepared_type = _prepare_menu_image(content, content_type)
    image_data = base64.b64encode(prepared_content).decode("ascii")
    prompt = """Read this restaurant menu and return ONLY valid JSON in this exact shape: {\"items\":[{\"category\":\"...\",\"name\":\"...\",\"description\":null,\"price\":123.0,\"available\":true}],\"warnings\":[\"...\"]}. Preserve visible item names and prices. Never invent a price. If a price is unreadable, omit that item and add a warning. Remove currency symbols from numeric prices. Infer categories only when clearly shown. Keep descriptions short."""

    configured_primary = os.getenv("OPENAI_MENU_MODEL", "gpt-4.1-mini").strip()
    configured_fallback = os.getenv("OPENAI_MENU_FALLBACK_MODEL", "gpt-4.1-nano").strip()
    models = []
    for model in (configured_primary, configured_fallback, "gpt-4o-mini", "gpt-4.1-nano"):
        if model and model not in models:
            models.append(model)

    detail = os.getenv("OPENAI_MENU_IMAGE_DETAIL", "low").strip().lower()
    if detail not in {"low", "high", "auto"}:
        detail = "low"

    payload = {
        "temperature": 0,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{prepared_type};base64,{image_data}", "detail": detail}},
            ],
        }],
    }

    response = None
    last_error = None
    for model in models:
        response = await _extract_with_model(payload, api_key, model)
        if response.status_code < 400:
            break
        try:
            error = response.json().get("error", {})
            code = error.get("code")
            last_error = error.get("message") or code
        except (ValueError, TypeError):
            code = None
            last_error = None
        if response.status_code == 429 and code == "insufficient_quota":
            break
        if response.status_code != 429:
            break

    if response is None:
        raise MenuImportError("AI menu extraction did not start.")

    if response.status_code >= 400:
        try:
            error = response.json().get("error", {})
            code = error.get("code")
            message = error.get("message")
        except (ValueError, TypeError):
            code = None
            message = last_error

        if response.status_code == 429 and code == "insufficient_quota":
            raise MenuImportError("OpenAI API quota is exhausted. Add API credits/billing to the OpenAI project used by OPENAI_API_KEY, then try again.")
        if response.status_code == 429:
            detail_text = message or "the configured vision models are temporarily rate-limited"
            raise MenuImportError(f"OpenAI menu extraction is rate-limited after trying multiple vision models: {detail_text}")
        if message:
            raise MenuImportError(f"OpenAI menu extraction failed: {message}")
        raise MenuImportError(f"AI menu extraction failed ({response.status_code}).")

    try:
        text = response.json()["choices"][0]["message"]["content"]
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        data = json.loads(text)
        items = [ImportedMenuItem.model_validate(item) for item in data.get("items", [])]
        warnings = [str(w) for w in data.get("warnings", [])]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MenuImportError("AI returned an unreadable menu. Please try a clearer image.") from exc

    return items, warnings
