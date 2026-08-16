import unittest

from fastapi import HTTPException

from app.api.dependencies import require_owner, require_staff


class FakeUser:
    def __init__(self, role: str):
        self.role = role


class AuthorizationDependencyTests(unittest.TestCase):
    def test_owner_allows_owner(self):
        self.assertEqual(require_owner(FakeUser("owner")), FakeUser("owner"))

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


if __name__ == "__main__":
    unittest.main()
