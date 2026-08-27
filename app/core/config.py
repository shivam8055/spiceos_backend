import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")


def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return list(dict.fromkeys([*origins, "https://app.spiceos.co.in"]))


CORS_ALLOWED_ORIGINS = _cors_origins()
PUBLIC_QR_BASE_URL = os.getenv("PUBLIC_QR_BASE_URL", "https://app.spiceos.co.in/#/order")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT in {"production", "prod"} or bool(os.getenv("RAILWAY_PROJECT_ID"))
QR_PUBLIC_TOKEN_SECRET = os.getenv("QR_PUBLIC_TOKEN_SECRET")
if not QR_PUBLIC_TOKEN_SECRET:
    if IS_PRODUCTION:
        raise RuntimeError("QR_PUBLIC_TOKEN_SECRET must be configured in production")
    QR_PUBLIC_TOKEN_SECRET = "spiceos-dev-qr-token-secret"

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MENU_MODEL = os.getenv("OPENAI_MENU_MODEL", "gpt-4.1-mini")

# WhatsApp Cloud API. Credentials stay in Railway environment variables.
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "spiceos-whatsapp-verify")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")
WHATSAPP_GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v23.0")
WHATSAPP_RESTAURANT_ID = os.getenv("WHATSAPP_RESTAURANT_ID")
WHATSAPP_DEFAULT_BRANCH_ID = os.getenv("WHATSAPP_DEFAULT_BRANCH_ID", "main")
# The menu displays 9661218183; WhatsApp click-to-chat requires the country code.
WHATSAPP_BUSINESS_NUMBER = os.getenv("WHATSAPP_BUSINESS_NUMBER", "919661218183")

UBER_DIRECT_CLIENT_ID = os.getenv("UBER_DIRECT_CLIENT_ID")
UBER_DIRECT_CLIENT_SECRET = os.getenv("UBER_DIRECT_CLIENT_SECRET")
UBER_DIRECT_CUSTOMER_ID = os.getenv("UBER_DIRECT_CUSTOMER_ID")
UBER_DIRECT_BASE_URL = os.getenv("UBER_DIRECT_BASE_URL", "https://api.uber.com")
RAPIDO_API_BASE_URL = os.getenv("RAPIDO_API_BASE_URL")
RAPIDO_API_KEY = os.getenv("RAPIDO_API_KEY")
OLA_API_BASE_URL = os.getenv("OLA_API_BASE_URL")
OLA_API_KEY = os.getenv("OLA_API_KEY")
