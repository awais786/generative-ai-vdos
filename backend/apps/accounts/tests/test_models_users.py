from django.test import TestCase
from django.db import IntegrityError
from apps.accounts.models import UserProfile


class UserProfileTest(TestCase):
    def _make_profile(self, sub="sub-123", email="a@example.com", name="Alice"):
        return UserProfile.objects.create(cognito_sub=sub, email=email, name=name)


    def test_cognito_sub_is_unique(self):
        self._make_profile()
        with self.assertRaises(IntegrityError):
            self._make_profile()  # same sub

    def test_name_is_optional(self):
        p = UserProfile.objects.create(cognito_sub="sub-456", email="b@example.com")
        self.assertEqual(p.name, "")

    def test_str(self):
        p = self._make_profile()
        self.assertIn("a@example.com", str(p))
