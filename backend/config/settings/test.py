from .base import *  # noqa: F401, F403

DEBUG = True
SESSION_COOKIE_SECURE = False
CORS_ALLOWED_ORIGINS = ["http://localhost:3000"]

# Dummy values so startup passes without real Cognito credentials.
# Individual tests override with self.settings(COGNITO=FAKE_COGNITO).
# Celery: run tasks synchronously in-process (no Redis required)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

FIELD_ENCRYPTION_KEY = "SgCzHjGtX6nlkiI4xmKwZJ85MTGdO-e2MiuUBN1v8JI="

STORAGES = {
    "default": {
        "BACKEND": "apps.storage.backends.ThumbnailInMemoryStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

COGNITO = {
    "COGNITO_DOMAIN": "https://test.auth.example.com",
    "COGNITO_APP_CLIENT_ID": "test-client-id",
    "COGNITO_APP_CLIENT_SECRET": "test-client-secret",
    "COGNITO_REDIRECT_URI": "http://localhost:8000/api/auth/callback",
    "COGNITO_LOGOUT_REDIRECT_URI": "http://localhost:3000",
}
