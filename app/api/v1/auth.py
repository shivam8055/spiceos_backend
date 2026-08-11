import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.firebase import initialize_firebase
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService


router = APIRouter()
security = HTTPBearer(auto_error=True)
logger = logging.getLogger(__name__)

initialize_firebase()


@router.get(
    "/me",
    response_model=UserResponse,
)
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    token = credentials.credentials.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Firebase Admin raises different exception types for malformed,
    # expired, revoked, and otherwise invalid ID tokens. Keep this boundary
    # deliberately broad: no Firebase exception should escape as a 500.
    try:
        decoded_token = auth.verify_id_token(token)
    except Exception as exc:
        logger.warning("Rejected Firebase ID token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    firebase_uid = decoded_token.get("uid")
    email = decoded_token.get("email")

    if not firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated Firebase user has no UID.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated Firebase user has no email.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        name = decoded_token.get("name")
        service = AuthService(db)
        user = service.get_or_create_user(
            firebase_uid=firebase_uid,
            email=email,
            name=name,
        )
    except Exception as exc:
        logger.exception("Failed to load SpiceOS user: %s", email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load the SpiceOS user profile.",
        ) from None

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    logger.info(
        "Authenticated SpiceOS user: %s (%s)",
        user.email,
        user.role,
    )

    return user
