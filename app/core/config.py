import os

from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")


def _cors_origins() -> list[str]:
    """Return normalized browser origins allowed to call the API.

    Railway environment variables are easy to accidentally configure with a
    trailing slash. Browsers send the origin without that slash, so normalize
    it here. The production SpiceOS app origin is also always retained so a
    bad/partial Railway override cannot silently break the deployed web app.
    """
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins = [
        origin.strip().rstrip("/")
        for origin in configured.split(",")
        if origin.strip()
    ]
    required = ["https://app.spiceos.co.in"]
    return list(dict.fromkeys([*origins, *required]))


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

# AI menu import configuration. The secret is supplied only through the
# deployment environment; never commit an API key to source control.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MENU_MODEL = os.getenv("OPENAI_MENU_MODEL", "gpt-4.1-mini")

# Third-party delivery provider credentials are intentionally optional.
# Provider adapters remain disabled until official credentials/access are supplied.
UBER_DIRECT_CLIENT_ID = os.getenv("UBER_DIRECT_CLIENT_ID")
UBER_DIRECT_CLIENT_SECRET = os.getenv("UBER_DIRECT_CLIENT_SECRET")
UBER_DIRECT_CUSTOMER_ID = os.getenv("UBER_DIRECT_CUSTOMER_ID")
UBER_DIRECT_BASE_URL = os.getenv("UBER_DIRECT_BASE_URL", "https://api.uber.com")
RAPIDO_API_BASE_URL = os.getenv("RAPIDO_API_BASE_URL")
RAPIDO_API_KEY = os.getenv("RAPIDO_API_KEY")
OLA_API_BASE_URL = os.getenv("OLA_API_BASE_URL")
OLA_API_KEY = os.getenv("OLA_API_KEY")
