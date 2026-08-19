import os

from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "https://app.spiceos.co.in").split(",")
    if origin.strip()
]

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
