from dotenv import load_dotenv
import os


load_dotenv()


DATABASE_URL = os.getenv("DATABASE_URL")

FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv(
    "FIREBASE_SERVICE_ACCOUNT_JSON"
)