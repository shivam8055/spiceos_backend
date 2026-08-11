from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_firebase_uid(
        self,
        firebase_uid: str,
    ) -> User | None:
        return (
            self.db.query(User)
            .filter(User.firebase_uid == firebase_uid)
            .first()
        )

    def get_by_email(
        self,
        email: str,
    ) -> User | None:
        return (
            self.db.query(User)
            .filter(User.email == email)
            .first()
        )

    def create_user(
        self,
        firebase_uid: str,
        email: str,
        name: str | None = None,
        role: str = "staff",
    ) -> User:
        user = User(
            firebase_uid=firebase_uid,
            email=email,
            name=name,
            role=role,
            is_active=True,
        )

        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        return user

    def update_user(
        self,
        user: User,
        *,
        email: str | None = None,
        name: str | None = None,
    ) -> User:
        if email is not None:
            user.email = email

        if name is not None:
            user.name = name

        self.db.commit()
        self.db.refresh(user)

        return user