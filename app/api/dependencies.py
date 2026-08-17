import logging
from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.firebase import initialize_firebase
from app.models.user import User
from app.services.auth_service import AuthService, FirebaseIdentityConflict

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    initialize_firebase()

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
        service = AuthService(db)
        user = service.get_or_create_user(
            firebase_uid=firebase_uid,
            email=email,
            name=decoded_token.get("name"),
        )
    except FirebaseIdentityConflict:
        db.rollback()
        logger.warning("Rejected Firebase identity conflict for email: %s", email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This email is already linked to another SpiceOS account.",
        ) from None
    except Exception:
        db.rollback()
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

    return user


def require_roles(*allowed_roles: str) -> Callable:
    def role_dependency(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )

        return current_user

    return role_dependency


require_owner = require_roles("owner")
require_staff = require_roles("manager", "staff", "owner")
