import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth

from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.firebase import initialize_firebase
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService


router = APIRouter()

security = HTTPBearer()

logger = logging.getLogger(__name__)


# Initialize Firebase Admin SDK before any authentication request.
initialize_firebase()


@router.get(
    "/me",
    response_model=UserResponse,
)
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(
        security
    ),
    db: Session = Depends(get_db),
):
    token = credentials.credentials

    try:
        decoded_token = auth.verify_id_token(token)

        firebase_uid = decoded_token["uid"]
        email = decoded_token.get("email")

        if not email:
            raise HTTPException(
                status_code=401,
                detail="Authenticated Firebase user has no email.",
            )

        name = decoded_token.get("name")

        service = AuthService(db)

        user = service.get_or_create_user(
            firebase_uid=firebase_uid,
            email=email,
            name=name,
        )

        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="User account is inactive.",
            )

        logger.info(
            "Authenticated SpiceOS user: %s (%s)",
            user.email,
            user.role,
        )

        return user

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Firebase authentication failed"
        )

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token.",
        ) from exc