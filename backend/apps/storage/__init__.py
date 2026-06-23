from pathlib import Path

from django.core.files import File
from django.core.files.storage import storages
from django.db.models.fields.files import FieldFile
from django.utils.functional import SimpleLazyObject


class StorageProvider:
    """
    Single facade over Django's configured storage backends — no local-vs-S3
    subclasses. Which backend is used is decided entirely by settings: the
    `backend` name is looked up in the STORAGES dict (edX-style selection on
    STORAGES['default']['BACKEND']), where 'default' resolves to
    FileSystemStorage in development, InMemoryStorage in tests, and
    S3Boto3Storage in production.

    There is no branching in url(): on S3 with querystring_auth=True the
    backend returns a presigned URL automatically; locally it returns a plain
    /media/… path. Expiry is governed by the backend's querystring_expire.
    """

    def __init__(self, backend: str = "default"):
        self.storage = storages[backend]

    def upload(self, field_file: FieldFile, local_path: Path, *, save: bool = True) -> None:
        """
        Write local_path into field_file via the configured storage backend.
        field_file.save() applies the field's upload_to key and persists the
        row when save=True; pass save=False to batch before a single .save().
        """
        with local_path.open("rb") as fh:
            field_file.save(local_path.name, File(fh), save=save)

    def url(self, field_file: FieldFile) -> str | None:
        """Access URL for field_file (presigned on S3), or None if empty."""
        if not field_file:
            return None
        # Expiry comes from the backend's querystring_expire. If per-call expiry
        # is ever needed, add expire=None here and pass it to storage.url(...).
        return self.storage.url(field_file.name)

    def thumbnails(self, field_file: FieldFile) -> dict[str, str]:
        """Map of ``{size_name: url}`` for field_file's thumbnails.

        Empty when the field is unset, the backend has no thumbnail support, or
        the file is not an image (e.g. a video). URLs are presigned on S3.
        """
        if not field_file:
            return {}
        storage = self.storage
        if not hasattr(storage, "get_thumbnails") or not storage.is_image(field_file.name):
            return {}
        return storage.get_thumbnails(field_file.name)


# Lazily built so importing this module never touches settings or the app
# registry before Django is ready. Usage from any app:
#   from apps.storage import storage_provider
#   storage_provider.upload(scene.media_path, disk_path)
#   storage_provider.url(scene.media_path)
storage_provider = SimpleLazyObject(StorageProvider)
