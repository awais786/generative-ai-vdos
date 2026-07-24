"""Single-node server deploy (EC2): production security without S3.

Use config.settings.production when AWS_STORAGE_BUCKET_NAME and Celery are
configured for a full cloud stack. The deploy scripts target this module.
"""
import os

from .base import *  # noqa: F401, F403
from .base import env_csv, require_cognito

DEBUG = False
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
ALLOWED_HOSTS = env_csv("DJANGO_ALLOWED_HOSTS")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

CORS_ALLOWED_ORIGINS = env_csv("CORS_ALLOWED_ORIGINS")

require_cognito()

CELERY_BROKER_URL = os.environ.get(
    "CELERY_BROKER_URL", "redis://127.0.0.1:6379/0",
)
CELERY_RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/0",
)
# Rollback toggle: set CELERY_EAGER=1 to revert to in-process execution if the
# worker unit is broken. NOTE: flipping this on while tasks are queued in Redis
# won't execute those queued tasks — drain or purge the queue first.
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_EAGER") == "1"
CELERY_TASK_EAGER_PROPAGATES = CELERY_TASK_ALWAYS_EAGER
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Use Redis DB 1 for Django cache so throttle counters and budget keys are
# isolated from the Celery broker on DB 0.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("DJANGO_CACHE_URL", "redis://127.0.0.1:6379/1"),
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO"},
        "pipeline": {"handlers": ["console"], "level": "INFO"},
    },
}
