import difflib
import json
import re
from datetime import datetime
from urllib.parse import quote
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session

from app.core.config import (
    OPENAI_API_KEY,
    OPENAI_MENU_MODEL,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_DEFAULT_BRANCH_ID,
    WHATSAPP_GRAPH_VERSION,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_RESTAURANT_ID,
    WHATSAPP_VERIFY_TOKEN,
)
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.whatsapp_session import WhatsAppSession
from app.services.qr_ordering import resolve_qr_table

QR_MARKER = re.compile(r"(?:SPICEOS[_ ]QR|SPICEOSQR)[:= ]([A-Za-z0-9_-]{20,})", re.I)


def whatsapp_qr_url(phone_number: str, qr_token: str | None = None, restaurant_id: str | None = None, branch_id: str | None = None) -> str:
    digits = re.sub(r"\D", "", phone_number)
    marker = f"SPICEOS_QR:{qr_token}" if qr_token else f"SPICEOS_ORDER:{restaurant_id or WHATSAPP_RESTAURANT_ID or ''}:{branch_id or WHATSAPP_DEFAULT_BRANCH_ID or ''}"
    return f"https://wa.me/{digits}?text={quote(marker)}"


def _normalize(value: str) -> str:
    value = value.lower().replace("×", "x")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _extract_quantity(text: str) -> tuple[int, str]:
    match = re.match(r"^\s*(\d+)\s*(?:x|pcs?|pieces?|plate|plates)?\s+(.+)$", text, re.I)
    if match:
        return max(1, min(int(match.group(1)), 50)), match.group(2).strip()
    return 1, text.strip()


def _split_order_text(text: str) -> list[str]:
    cleaned = re.sub(r"\b(?:please|pls|order|give|send|add|i want|i need)\b", " ", text, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
    return [part.strip() for part in re.split(r"\s*(?:,|\+|\band\b)\s*", cleaned, flags=re.I) if part.strip()]


def _fuzzy_match(parts: list[str], menu: list[MenuItem]) -> list[dict]:
    names = {_normalize(item.name): item for item in menu}
    output = []
    for part in parts:
        quantity, name_text = _extract_quantity(part)
        target = _normalize(name_text)
        if not target:
            continue
        exact = names.get(target)
        if exact:
            output.append({"menu_item_id": exact.id, "quantity": quantity, "note": None})
            continue
        candidates = difflib.get_close_matches(target, list(names.keys()), n=1, cutoff=0.60)
        if candidates:
            item = names[candidates[0]]
            output.append({"menu_item_id": item.id, "quantity": quantity, "note": None})
    return output


async def _ai_parse_order(text: str, menu: list[MenuItem]) -> list[dict]:
    if not OPENAI_API_KEY:
        return _fuzzy_match(_split_order_text(text), menu)
    catalog = [{"id": item.id, "name": item.name, "category": item.category, "price": float(item.price)} for item in menu if item.available]
    prompt = (
        "You are the SpiceOS WhatsApp food-order parser. Match the customer's message only to the supplied menu. "
        "Never invent an item. Return JSON only as {\"items\":[{\"menu_item_id\":number,\"quantity\":number,\"note\":string|null}]}. "
        "Use quantity 1 when omitted. Omit anything that is not on the menu.\n\n"
        f"MENU={json.dumps(catalog, ensure_ascii=False)}\nCUSTOMER={text}"
    )
    body = {"model": OPENAI_MENU_MODEL, "messages": [{"role": "system", "content": "Return valid JSON only."}, {"role": "user", "content": prompt}], "temperature": 0, "response_format": {"type": "json_object"}}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}, json=body)
            response.raise_for_status()
            parsed = json.loads(response.json()["choices"][0]["message"]["content"])
        valid_ids = {item.id for item in menu if item.available}
        result = []
        for row in parsed.get("items", []) if isinstance(parsed, dict) else []:
            try:
                item_id = int(row["menu_item_id"])
                quantity = max(1, min(int(row.get("quantity", 1)), 50))
            except (KeyError, TypeError, ValueError):
                continue
            if item_id in valid_ids:
                result.append({"menu_item_id": item_id, "quantity": quantity, "note": row.get("note")})
        if result:
            return result
    except Exception:
        pass
    return _fuzzy_match(_split_order_text(text), menu)


def _menu_for_session(db: Session, session: WhatsAppSession) -> list[MenuItem]:
    if not session.restaurant_id or not session.branch_id:
        return []
    return db.query(MenuItem).filter(MenuItem.restaurant_id == session.restaurant_id, MenuItem.branch_id == session.branch_id, MenuItem.available.is_(True)).order_by(MenuItem.category.asc(), MenuItem.name.asc()).all()


def _resolve_context(db: Session, marker: str | None) -> tuple[str | None, str | None, str | None]:
    if marker:
        qr_match = QR_MARKER.search(marker)
        if qr_match:
            try:
                table = resolve_qr_table(db, qr_match.group(1))
                return table.restaurant_id, table.branch_id, qr_match.group(1)
            except Exception:
                pass
        match = re.search(r"SPICEOS_ORDER:([^: ]+):([^ ]+)", marker, re.I)
        if match:
            return match.group(1), match.group(2), None
    return WHATSAPP_RESTAURANT_ID, WHATSAPP_DEFAULT_BRANCH_ID, None


def _get_session(db: Session, wa_id: str) -> WhatsAppSession:
    session = db.query(WhatsAppSession).filter(WhatsAppSession.wa_id == wa_id).first()
    if session is None:
        session = WhatsAppSession(wa_id=wa_id, state="awaiting_order", draft_json="{}")
        db.add(session)
        db.flush()
    return session


def _draft(session: WhatsAppSession) -> dict:
    try:
        value = json.loads(session.draft_json or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _save_draft(session: WhatsAppSession, value: dict) -> None:
    session.draft_json = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    session.updated_at = datetime.utcnow()


def _format_cart(menu: list[MenuItem], items: list[dict]) -> tuple[str, float]:
    by_id = {item.id: item for item in menu}
    lines, total = [], 0.0
    for row in items:
        item = by_id.get(int(row["menu_item_id"]))
        if not item:
            continue
        qty = int(row["quantity"])
        line = float(item.price) * qty
        total += line
        lines.append(f"• {item.name} x{qty} — ₹{line:.0f}")
    return "\n".join(lines), total


def _create_order(db: Session, session: WhatsAppSession, items: list[dict]) -> Order:
    menu = _menu_for_session(db, session)
    by_id = {item.id: item for item in menu}
    if not items:
        raise ValueError("No valid menu items")
    total, snapshots = 0.0, []
    for row in items:
        item = by_id.get(int(row["menu_item_id"]))
        if not item or not item.available:
            raise ValueError("One or more items are unavailable")
        qty = max(1, min(int(row["quantity"]), 50))
        line_total = float(item.price) * qty
        total += line_total
        snapshots.append((item, qty, line_total, row.get("note")))
    order = Order(order_number=f"WA-{uuid4().hex[:12].upper()}", restaurant_id=session.restaurant_id, customer_id=None, customer_name=(session.customer_name or "WhatsApp Customer").strip(), customer_phone=session.customer_phone or session.wa_id, primary_item=snapshots[0][0].name, total=round(total, 2), status="created", payment_status="pending", order_source="whatsapp", idempotency_key=f"whatsapp:{session.wa_id}:{uuid4().hex}", created_at=datetime.utcnow())
    db.add(order)
    db.flush()
    for item, qty, line_total, note in snapshots:
        db.add(OrderItem(order_id=order.id, menu_item_id=item.id, item_name=item.name, quantity=qty, unit_price=float(item.price), modifiers_json="[]", line_total=line_total, note=note))
    db.commit()
    db.refresh(order)
    return order


def _help_message(menu: list[MenuItem]) -> str:
    categories = list(dict.fromkeys(item.category for item in menu))
    return "Welcome to Spice Box! 🌶️\nSend your order naturally, for example:\n2 Chicken Biryani, 1 Paneer Tikka\n\nCategories: " + ", ".join(categories[:12]) + "\nI’ll make the cart, show the total, and ask you to confirm."


async def handle_incoming_message(db: Session, wa_id: str, message_id: str, text: str, profile_name: str | None = None) -> str:
    session = _get_session(db, wa_id)
    if session.last_message_id == message_id:
        return ""
    session.last_message_id = message_id
    if profile_name and not session.customer_name:
        session.customer_name = profile_name
    session.customer_phone = wa_id
    if not session.restaurant_id or not session.branch_id:
        restaurant_id, branch_id, qr_token = _resolve_context(db, text)
        session.restaurant_id, session.branch_id, session.qr_token = restaurant_id, branch_id, qr_token
    menu = _menu_for_session(db, session)
    if not menu:
        db.commit()
        return "SpiceOS ordering is not configured for this WhatsApp number yet. Please contact the restaurant."
    lower = text.strip().lower()
    if lower in {"hi", "hello", "hey", "menu", "start", "order"} or lower.startswith("spiceos_"):
        session.state = "awaiting_order"
        _save_draft(session, {})
        db.commit()
        return _help_message(menu)
    if session.state == "awaiting_confirmation":
        if lower in {"yes", "y", "confirm", "confirmed", "place order", "place"}:
            try:
                order = _create_order(db, session, _draft(session).get("items", []))
            except ValueError:
                session.state = "awaiting_order"
                db.commit()
                return "Sorry, one of the items changed availability. Please send the order again."
            session.state = "awaiting_order"
            _save_draft(session, {})
            db.commit()
            return f"✅ Order confirmed!\nOrder: {order.order_number}\nTotal: ₹{order.total:.0f}\n\nWe’ve sent it to the SpiceOS kitchen."
        if lower in {"no", "n", "cancel", "change", "edit"}:
            session.state = "awaiting_order"
            db.commit()
            return "No problem. Tell me what you’d like to change."
    items = await _ai_parse_order(text, menu)
    if not items:
        db.commit()
        return "I couldn’t match that to the menu. Please send item names and quantities, e.g. ‘2 Chicken Biryani, 1 Veg Momos’."
    cart_text, total = _format_cart(menu, items)
    _save_draft(session, {"items": items})
    session.state = "awaiting_confirmation"
    db.commit()
    return f"🧾 Your Spice Box order:\n{cart_text}\n\nTotal: ₹{total:.0f}\n\nReply *CONFIRM* to place the order or *CHANGE* to edit it."


async def send_whatsapp_text(to: str, body: str) -> None:
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError("WhatsApp Cloud API credentials are not configured")
    url = f"https://graph.facebook.com/{WHATSAPP_GRAPH_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "text", "text": {"preview_url": False, "body": body[:4096]}}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"}, json=payload)
        response.raise_for_status()


def verify_webhook_token(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    if mode == "subscribe" and token and token == WHATSAPP_VERIFY_TOKEN and challenge:
        return challenge
    return None
