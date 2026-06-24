"""Thumbnail-generating storage backends.

Each wraps one of the backends used across environments (S3 in production,
FileSystem in development, InMemory in tests) with ``ThumbnailMixin`` from the
reusable ``django-storage-thumbnails`` package. Point
``STORAGES["default"]["BACKEND"]`` at the appropriate one per settings module;
the rest of the app keeps using the ``storage_provider`` facade unchanged.
"""

from django.core.files.storage import FileSystemStorage, InMemoryStorage
from storages.backends.s3boto3 import S3Boto3Storage
from thumbnail_storage import ThumbnailMixin


class ThumbnailS3Storage(ThumbnailMixin, S3Boto3Storage):
    """Production S3 storage that also generates image thumbnails."""


class ThumbnailFileSystemStorage(ThumbnailMixin, FileSystemStorage):
    """Local-filesystem storage (development) that generates thumbnails."""


class ThumbnailInMemoryStorage(ThumbnailMixin, InMemoryStorage):
    """In-memory storage (tests) that generates thumbnails."""
