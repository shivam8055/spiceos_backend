import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.api.dependencies import require_owner, require_staff
from app.services.auth_service import AuthService, FirebaseIdentityConflict


class FakeUser:
    def __init__(self, role: str):
        self.role = role


class AuthorizationDependencyTests(unittest.TestCase):
    def test_owner_allows_owner(self):
        user = FakeUser("owner")
        self.assertIs(require_owner(user), user)

    def test_owner_rejects_manager_with_403(self):
        with self.assertRaises(HTTPException) as context:
            require_owner(FakeUser("manager"))
        self.assertEqual(context.exception.status_code, 403)

    def test_owner_rejects_staff_with_403(self):
        with self.assertRaises(HTTPException) as context:
            require_owner(FakeUser("staff"))
        self.assertEqual(context.exception.status_code, 403)

    def test_staff_allows_manager(self):
        user = FakeUser("manager")
        self.assertIs(require_staff(user), user)

    def test_staff_allows_staff(self):
        user = FakeUser("staff")
        self.assertIs(require_staff(user), user)

    def test_staff_allows_owner(self):
        user = FakeUser("owner")
        self.assertIs(require_staff(user), user)

    def test_staff_rejects_unknown_role_with_403(self):
        with self.assertRaises(HTTPException) as context:
            require_staff(FakeUser("customer"))
        self.assertEqual(context.exception.status_code, 403)


class FirebaseIdentityBindingTests(unittest.TestCase):
    @patch("app.services.auth_service.UserRepository")
    def test_existing_email_bound_to_different_uid_is_rejected(self, repository_class):
        repository = repository_class.return_value
        existing_user = Mock(firebase_uid="existing-firebase-uid")
        repository.get_by_firebase_uid.return_value = None
        repository.get_by_email.return_value = existing_user

        service = AuthService(Mock())
        with self.assertRaises(FirebaseIdentityConflict):
            service.get_or_create_user(
                firebase_uid="different-firebase-uid",
                email="owner@example.com",
                name="Owner",
            )

        repository.create_user.assert_not_called()


if __name__ == "__main__":
    unittest.main()
