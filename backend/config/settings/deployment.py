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
# Single-node bootstrap: run tasks in-process until a Celery worker unit is added.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

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
