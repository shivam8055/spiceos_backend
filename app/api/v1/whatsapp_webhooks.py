import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_staff
from app.core.config import WHATSAPP_APP_SECRET, WHATSAPP_BUSINESS_NUMBER
from app.core.database import get_db
from app.models.user import User
from app.services.whatsapp_ordering import handle_incoming_message, send_whatsapp_text, verify_webhook_token, whatsapp_qr_url

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


def _verify_signature(raw_body: bytes, signature: str | None) -> bool:
    if not WHATSAPP_APP_SECRET:
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(WHATSAPP_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


@router.get("")
async def verify_whatsapp_webhook(request: Request):
    challenge = verify_webhook_token(request.query_params.get("hub.mode"), request.query_params.get("hub.verify_token"), request.query_params.get("hub.challenge"))
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed")
    return int(challenge) if challenge.isdigit() else challenge


@router.post("")
async def receive_whatsapp_webhook(request: Request, db: Session = Depends(get_db), x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256")):
    raw_body = await request.body()
    if not _verify_signature(raw_body, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid WhatsApp webhook signature")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON") from exc
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = value.get("contacts", [])
            profile_name = (contacts[0].get("profile") or {}).get("name") if contacts else None
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue
                wa_id, message_id = message.get("from"), message.get("id")
                text = ((message.get("text") or {}).get("body") or "").strip()
                if not wa_id or not message_id or not text:
                    continue
                reply = await handle_incoming_message(db, wa_id, message_id, text, profile_name)
                if reply:
                    await send_whatsapp_text(wa_id, reply)
    return {"ok": True}


@router.get("/admin/qr-link")
def get_whatsapp_qr_link(qr_token: str | None = None, restaurant_id: str | None = None, branch_id: str | None = None, current_user: User = Depends(require_staff)):
    return {"phone": WHATSAPP_BUSINESS_NUMBER, "url": whatsapp_qr_url(WHATSAPP_BUSINESS_NUMBER, qr_token=qr_token, restaurant_id=restaurant_id, branch_id=branch_id)}
