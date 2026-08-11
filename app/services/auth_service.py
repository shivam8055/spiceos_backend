from sqlalchemy.orm import Session

from app.repositories.user_repository import UserRepository


OWNER_EMAIL = "admin@spiceos.co.in"


class AuthService:
    def __init__(self, db: Session):
        self.repository = UserRepository(db)

    def get_or_create_user(
        self,
        firebase_uid: str,
        email: str,
        name: str | None = None,
    ):
        user = self.repository.get_by_firebase_uid(
            firebase_uid
        )

        if user:
            return self.repository.update_user(
                user,
                email=email,
                name=name,
            )

        existing_email_user = self.repository.get_by_email(
            email
        )

        if existing_email_user:
            return existing_email_user

        role = (
            "owner"
            if email.lower() == OWNER_EMAIL.lower()
            else "staff"
        )

        return self.repository.create_user(
            firebase_uid=firebase_uid,
            email=email,
            name=name,
            role=role,
        )