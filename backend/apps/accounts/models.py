from django.db import models

from apps.core.models import Provider, TimestampMixin
from pipeline.secure import SecureString, encrypt_string


class UserProfile(TimestampMixin):
    cognito_sub = models.CharField(max_length=128, unique=True)
    email = models.EmailField(max_length=254)
    name = models.CharField(max_length=200, blank=True, default="")

    @property
    def is_authenticated(self):
        return True

    def __str__(self):
        return self.email


class UserAPIKey(TimestampMixin):
    owner        = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="api_keys")
    provider     = models.ForeignKey(
        Provider, on_delete=models.PROTECT, related_name="user_keys",
    )
    _api_key_enc = models.BinaryField(editable=False)
    key_hint     = models.CharField(max_length=12, editable=False, default="")
    label        = models.CharField(max_length=100, blank=True, default="")
    # Optional per-provider endpoint override — currently only meaningful for
    # DashScope, whose workspace URL varies per account.
    api_url      = models.URLField(max_length=500, blank=True, default="")

    class Meta:
        verbose_name = "User API Key"
        verbose_name_plural = "User API Keys"
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "provider"],
                name="unique_owner_provider_key",
            ),
        ]

    def __str__(self):
        return f"{self.owner.email} — {self.provider.name}"

    def set_api_key(self, plaintext: str):
        if not plaintext or not plaintext.strip():
            raise ValueError("API key must not be empty")
        if len(plaintext) < 8:
            raise ValueError("API key must be at least 8 characters")
        self._api_key_enc = encrypt_string(plaintext)
        if len(plaintext) <= 8:
            self.key_hint = "••••••••"
        else:
            self.key_hint = plaintext[:4] + "••••" + plaintext[-4:]

    def get_secure_key(self) -> SecureString:
        return SecureString(bytes(self._api_key_enc), api_url=self.api_url or None)
