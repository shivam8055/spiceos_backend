import os

from dotenv import load_dotenv


load_dotenv()


DATABASE_URL = os.getenv("DATABASE_URL")

FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv(
    "FIREBASE_SERVICE_ACCOUNT_JSON"
)

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "https://app.spiceos.co.in",
    ).split(",")
    if origin.strip()
]

# Flutter web uses hash routing in the current frontend. The QR URL must put
# the customer route inside the hash; otherwise GoRouter sees the fragment
# (/menu) and opens the staff menu screen instead of the public order screen.
PUBLIC_QR_BASE_URL = os.getenv(
    "PUBLIC_QR_BASE_URL",
    "https://app.spiceos.co.in/#/order",
)

# The QR signing secret must be stable in production. Keep a development
# fallback for local work, but never allow a known default secret to be used
# by a production deployment. Railway exposes RAILWAY_PROJECT_ID, so Railway
# deployments are treated as production unless an explicit development/test
# environment is selected.
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT in {"production", "prod"} or bool(
    os.getenv("RAILWAY_PROJECT_ID")
)
QR_PUBLIC_TOKEN_SECRET = os.getenv("QR_PUBLIC_TOKEN_SECRET")
if not QR_PUBLIC_TOKEN_SECRET:
    if IS_PRODUCTION:
        raise RuntimeError(
            "QR_PUBLIC_TOKEN_SECRET must be configured in production"
        )
    QR_PUBLIC_TOKEN_SECRET = "spiceos-dev-qr-token-secret"

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
