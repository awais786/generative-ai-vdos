import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

_repo_root = BASE_DIR.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
try:
    from pipeline.env import load_env
    load_env()
except ImportError:
    pass

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-change-in-prod")

FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", "")

DEBUG = False

ALLOWED_HOSTS: list[str] = []


def env_csv(name, default=""):
    """Comma-separated env var → list, dropping empty entries.

    Avoids the "".split(",") == [""] footgun that yields an invalid
    single-element host/origin list when the var is unset.
    """
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


_COGNITO_VARS = (
    "COGNITO_DOMAIN",
    "COGNITO_APP_CLIENT_ID",
    "COGNITO_APP_CLIENT_SECRET",
    "COGNITO_REDIRECT_URI",
    "COGNITO_LOGOUT_REDIRECT_URI",
)
COGNITO = {k: os.environ.get(k, "") for k in _COGNITO_VARS}


def require_cognito():
    """Raise if any COGNITO var is unset — called by non-test settings."""
    missing = [k for k, v in COGNITO.items() if not v]
    if missing:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(f"Missing COGNITO env vars: {', '.join(missing)}")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "storages",
    "apps.health",
    "apps.core",
    "apps.accounts",
    "apps.projects",
    "apps.storage",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = True

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

# Block vulgar/offensive user input (local blocklist + OpenAI moderation when key set).
CONTENT_MODERATION_ENABLED = env_bool("CONTENT_MODERATION_ENABLED", False)

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS: list[str] = []

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.CognitoSessionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "static/"

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
