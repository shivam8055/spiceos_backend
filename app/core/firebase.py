import json
import os

import firebase_admin
from firebase_admin import credentials


FIREBASE_PROJECT_ID = "spicebox-133b4"


def initialize_firebase() -> None:
    if firebase_admin._apps:
        return

    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    service_account_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if service_account_json:
        try:
            service_account_info = json.loads(service_account_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "FIREBASE_SERVICE_ACCOUNT_JSON contains invalid JSON."
            ) from exc

        credential = credentials.Certificate(service_account_info)

    elif service_account_path:
        if not os.path.isfile(service_account_path):
            raise RuntimeError(
                "Firebase service-account file was not found at: "
                f"{service_account_path}"
            )

        credential = credentials.Certificate(service_account_path)

    else:
        raise RuntimeError(
            "Firebase credentials are not configured. "
            "Set GOOGLE_APPLICATION_CREDENTIALS to the path "
            "of your Firebase service-account JSON file."
        )

    firebase_admin.initialize_app(
        credential,
        {
            "projectId": FIREBASE_PROJECT_ID,
        },
    )