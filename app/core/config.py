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

QR_PUBLIC_TOKEN_SECRET = os.getenv("QR_PUBLIC_TOKEN_SECRET")
if not QR_PUBLIC_TOKEN_SECRET:
    # Development fallback only. Production deployments must provide a stable secret.
    QR_PUBLIC_TOKEN_SECRET = "spiceos-dev-qr-token-secret"
