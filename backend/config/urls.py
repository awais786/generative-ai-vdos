import re

from django.contrib import admin
from django.conf import settings
from django.urls import path, re_path, include
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.health.urls")),
    path("api/core/", include("apps.core.urls")),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.projects.urls")),
]

if settings.STORAGES["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage":
    # django.conf.urls.static.static() no-ops unless DEBUG=True, so it can't be
    # used here: local-disk deploys (dev, and the single-node EC2 deploy in
    # config.settings.deployment, which runs with DEBUG=False) still need
    # Django to serve /media/ itself — nginx proxies it there
    # (scripts/deploy/nginx.conf). S3 deploys never reach this branch:
    # production.py points STORAGES at S3Boto3Storage instead.
    urlpatterns += [
        re_path(
            r"^%s(?P<path>.*)$" % re.escape(settings.MEDIA_URL.lstrip("/")),
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
