import base64
import json
import os
import re

import httpx

from app.schemas.menu_import import ImportedMenuItem


class MenuImportError(RuntimeError):
    pass


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

    payload = {
        "model": os.getenv("OPENAI_MENU_MODEL", "gpt-4.1-mini"),
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{image_data}"}},
            ],
        }],
    }

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )

    if response.status_code >= 400:
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
