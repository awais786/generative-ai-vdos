import os
from botocore.config import Config as BotoConfig
from .base import *  # noqa: F401, F403
from .base import env_bool, env_csv, require_cognito

DEBUG = False
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
ALLOWED_HOSTS = env_csv("DJANGO_ALLOWED_HOSTS")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = not env_bool("DISABLE_SSL_REDIRECT", default=False)
# TLS terminates at the load balancer / CDN and forwards plain HTTP, so trust the
# X-Forwarded-Proto header to know the original request was HTTPS. Without this,
# SECURE_SSL_REDIRECT would 301-loop forever and secure cookies/HSTS never apply.
# Only safe because the proxy is trusted to set this header (clients can't reach
# the app server directly to spoof it).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

CORS_ALLOWED_ORIGINS = env_csv("CORS_ALLOWED_ORIGINS")

require_cognito()

# Celery: real broker (Redis) in production
CELERY_BROKER_URL = os.environ["CELERY_BROKER_URL"]
CELERY_RESULT_BACKEND = os.environ["CELERY_RESULT_BACKEND"]

AWS_STORAGE_BUCKET_NAME = os.environ["AWS_STORAGE_BUCKET_NAME"]
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "us-east-1")

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "region_name": AWS_S3_REGION_NAME,
            # ACLs are disabled by default on buckets created since Apr 2023;
            # passing an ACL ("private") would raise AccessControlListNotSupported.
            # None lets the bucket policy + Block Public Access enforce privacy,
            # while querystring_auth=True still serves objects via presigned URLs.
            "default_acl": None,
            "file_overwrite": False,
            "querystring_auth": True,
            "querystring_expire": 3600,
            # Tighter timeouts + adaptive retry so a stalled S3 connection
            # fails in ~30s instead of the boto3 default 60s, avoiding the
            # 2-min hangs we saw on first-run assembly when a parallel GET
            # got stuck on a stale keep-alive after the prior PUT-heavy stages.
            "client_config": BotoConfig(
                connect_timeout=10,
                read_timeout=30,
                retries={"max_attempts": 4, "mode": "adaptive"},
                max_pool_connections=20,
            ),
        },
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
