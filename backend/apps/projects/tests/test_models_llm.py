import os

from django.conf import settings
from django.db import IntegrityError
from django.test import TestCase

from apps.accounts.models import UserAPIKey, UserProfile
from apps.core.models import Provider
from apps.projects.choices import Capability
from apps.projects.models import LLMModel
from pipeline.secure import get_fernet


def _provider(code="openai", name="OpenAI"):
    return Provider.objects.create(code=code, name=name)


def _llm(provider=None, **kwargs):
    defaults = {
        "provider": provider or _provider(),
        "capability": Capability.PLAN,
        "model_id": "gpt-4o-mini",
        "display_name": "GPT-4o Mini",
    }
    defaults.update(kwargs)
    return LLMModel.objects.create(**defaults)


class ProviderTest(TestCase):
    def test_create(self):
        p = _provider()
        self.assertEqual(p.code, "openai")
        self.assertTrue(p.is_active)

    def test_unique_code(self):
        _provider(code="x")
        with self.assertRaises(IntegrityError):
            _provider(code="x", name="X2")

    def test_str(self):
        self.assertEqual(str(_provider(name="Google")), "Google")


class LLMModelTest(TestCase):
    def test_unique_constraint(self):
        p = _provider()
        _llm(provider=p, model_id="m1")
        with self.assertRaises(IntegrityError):
            _llm(provider=p, model_id="m1")

    def test_protect_on_provider_delete(self):
        p = _provider()
        _llm(provider=p)
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            p.delete()

    def test_is_default_save_guard(self):
        p = _provider()
        m1 = _llm(provider=p, model_id="m1", is_default=True)
        m2 = _llm(provider=p, model_id="m2", is_default=True)
        m1.refresh_from_db()
        self.assertFalse(m1.is_default)
        self.assertTrue(m2.is_default)

    def test_is_default_different_capability(self):
        p = _provider()
        m1 = _llm(provider=p, model_id="plan-m", capability=Capability.PLAN, is_default=True)
        m2 = _llm(provider=p, model_id="img-m", capability=Capability.IMAGE, is_default=True)
        m1.refresh_from_db()
        self.assertTrue(m1.is_default)
        self.assertTrue(m2.is_default)

    def test_str(self):
        p = _provider(code="google", name="Google")
        m = _llm(provider=p, display_name="Gemini Flash")
        self.assertEqual(str(m), "Gemini Flash (google)")


class UserAPIKeyTest(TestCase):
    def setUp(self):
        os.environ["FIELD_ENCRYPTION_KEY"] = settings.FIELD_ENCRYPTION_KEY
        get_fernet.cache_clear()

    def tearDown(self):
        get_fernet.cache_clear()

    def _make_key(self, plaintext="sk-test-key-12345678"):
        user = UserProfile.objects.create(cognito_sub="sub-1", email="a@b.com")
        provider = _provider()
        key = UserAPIKey(owner=user, provider=provider)
        key.set_api_key(plaintext)
        key.save()
        return key

    def test_encrypt_decrypt_round_trip(self):
        key = self._make_key("sk-abcdefgh12345678")
        self.assertEqual(key.get_secure_key().decrypt(), "sk-abcdefgh12345678")

    def test_key_hint_long(self):
        key = self._make_key("sk-abcdefgh12345678")
        self.assertEqual(key.key_hint, "sk-a••••5678")

    def test_key_hint_short(self):
        key = self._make_key("12345678")
        self.assertEqual(key.key_hint, "••••••••")

    def test_empty_key_raises(self):
        with self.assertRaises(ValueError):
            self._make_key("")

    def test_short_key_raises(self):
        with self.assertRaises(ValueError):
            self._make_key("short")

    def test_unique_owner_provider(self):
        key = self._make_key()
        key2 = UserAPIKey(owner=key.owner, provider=key.provider)
        key2.set_api_key("sk-another-key-here")
        with self.assertRaises(IntegrityError):
            key2.save()

    def test_protect_on_provider_delete(self):
        key = self._make_key()
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            key.provider.delete()
