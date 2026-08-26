import asyncio
import base64
import json
import os
import re

import httpx

from app.schemas.menu_import import ImportedMenuItem


class MenuImportError(RuntimeError):
    pass


async def _openai_extract(payload: dict, api_key: str) -> httpx.Response:
    """Call OpenAI with bounded exponential backoff for transient rate limits."""
    async with httpx.AsyncClient(timeout=90) as client:
        for attempt in range(4):
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code != 429 or attempt == 3:
                return response

            # A depleted quota cannot be fixed by retrying or changing models.
            try:
                error = response.json().get("error", {})
                if error.get("code") == "insufficient_quota":
                    return response
            except (ValueError, TypeError):
                pass

            retry_after = response.headers.get("retry-after")
            try:
                delay = min(float(retry_after), 15.0) if retry_after else min(2.0 ** (attempt + 1), 15.0)
            except ValueError:
                delay = min(2.0 ** (attempt + 1), 15.0)
            await asyncio.sleep(delay)

    raise RuntimeError("OpenAI request failed unexpectedly.")


async def _extract_with_model(payload: dict, api_key: str, model: str) -> httpx.Response:
    payload = {**payload, "model": model}
    return await _openai_extract(payload, api_key)


async def extract_menu_from_image(content: bytes, content_type: str) -> tuple[list[ImportedMenuItem], list[str]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise MenuImportError("AI menu import is not configured. Set OPENAI_API_KEY on the backend.")

    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise MenuImportError("Please upload a JPG, PNG, or WEBP menu image.")
    if len(content) > 15 * 1024 * 1024:
        raise MenuImportError("Menu image is too large. Maximum size is 15 MB.")

    image_data = base64.b64encode(content).decode("ascii")
    prompt = """Extract the restaurant menu from this image. Return ONLY valid JSON with this exact shape: {\"items\":[{\"category\":\"...\",\"name\":\"...\",\"description\":null,\"price\":123.0,\"available\":true}],\"warnings\":[\"...\"]}.\nRules: preserve item names and prices exactly as visible; do not invent missing prices; if a price is unreadable, omit that item and add a warning; normalize currency symbols out of price; use numeric price; infer category only when clearly indicated by the menu layout; keep descriptions short; do not create modifiers from guesses."""

    primary_model = os.getenv("OPENAI_MENU_MODEL", "gpt-4.1-mini")
    fallback_model = os.getenv("OPENAI_MENU_FALLBACK_MODEL", "gpt-4.1-nano")
    payload = {
        "temperature": 0,
        "max_tokens": 1800,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{image_data}", "detail": "high"}},
            ],
        }],
    }

    response = await _extract_with_model(payload, api_key, primary_model)

    # A model-specific 429 can occur even when the key/project is otherwise valid.
    # Give a smaller vision model one bounded fallback attempt after the primary
    # model's retries. This keeps imports usable under bursty/token-specific limits.
    if response.status_code == 429:
        try:
            error = response.json().get("error", {})
            code = error.get("code")
        except (ValueError, TypeError):
            code = None
        if code != "insufficient_quota" and fallback_model and fallback_model != primary_model:
            fallback_payload = {
                **payload,
                "max_tokens": 1200,
            }
            response = await _extract_with_model(fallback_payload, api_key, fallback_model)

    if response.status_code >= 400:
        try:
            error = response.json().get("error", {})
            code = error.get("code")
            message = error.get("message")
        except (ValueError, TypeError):
            code = None
            message = None

        if response.status_code == 429 and code == "insufficient_quota":
            raise MenuImportError("OpenAI API quota is exhausted. Add API credits/billing to the OpenAI project used by OPENAI_API_KEY, then try again.")
        if response.status_code == 429:
            raise MenuImportError("OpenAI is temporarily rate-limiting menu extraction. SpiceOS retried and also tried its fallback vision model. Please wait a little and try again.")
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
