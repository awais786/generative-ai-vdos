"""Thumbnail generation through the configured storage backend.

Runs under config.settings.test (ThumbnailInMemoryStorage + THUMBNAIL_SIZES from
base settings), so these exercise the real save path: storage_provider.upload ->
FieldFile.save -> storage._save -> ThumbnailMixin.
"""

import tempfile
from pathlib import Path

from django.test import TestCase
from PIL import Image

from apps.accounts.models import UserProfile
from apps.projects.models import Project, Scene
from apps.projects.serializers import SceneSerializer
from apps.storage import storage_provider

SIZES = ("thumb", "small")


def _img_tmp(width=640, height=360, suffix=".png") -> Path:
    fmt = "PNG" if suffix == ".png" else "JPEG"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        Image.new("RGB", (width, height), (30, 144, 255)).save(f, format=fmt)
        f.flush()
        return Path(f.name)


def _bytes_tmp(data=b"not an image", suffix=".mp4") -> Path:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(data)
        f.flush()
        return Path(f.name)


class SceneThumbnailTests(TestCase):
    def setUp(self):
        owner = UserProfile.objects.create(cognito_sub="sub-thumb", email="t@test.com")
        self.project = Project.objects.create(owner=owner, prompt="thumbs")
        self.scene = Scene.objects.create(
            project=self.project, index=0, narration="n", media_prompt="p"
        )
        self.storage = storage_provider.storage

    def test_thumbnails_created_on_image_upload(self):
        storage_provider.upload(self.scene.media_path, _img_tmp())
        name = self.scene.media_path.name
        for key in SIZES:
            thumb = self.storage.get_thumbnail_name(name, key)
            self.assertTrue(self.storage.exists(thumb), f"{thumb} missing")
            with self.storage.open(thumb) as fh:
                img = Image.open(fh)
                img.load()
            self.assertLessEqual(img.width, {"thumb": 320, "small": 160}[key])

    def test_facade_returns_thumbnail_urls(self):
        storage_provider.upload(self.scene.media_path, _img_tmp())
        urls = storage_provider.thumbnails(self.scene.media_path)
        self.assertEqual(set(urls), set(SIZES))
        self.assertTrue(all(urls.values()))

    def test_non_image_has_no_thumbnails(self):
        storage_provider.upload(self.scene.media_path, _bytes_tmp(suffix=".mp4"))
        name = self.scene.media_path.name
        self.assertEqual(storage_provider.thumbnails(self.scene.media_path), {})
        self.assertFalse(self.storage.exists(self.storage.get_thumbnail_name(name, "thumb")))

    def test_empty_media_path_returns_empty(self):
        self.assertEqual(storage_provider.thumbnails(self.scene.media_path), {})

    def test_delete_removes_thumbnails(self):
        storage_provider.upload(self.scene.media_path, _img_tmp())
        name = self.scene.media_path.name
        thumb = self.storage.get_thumbnail_name(name, "thumb")
        self.assertTrue(self.storage.exists(thumb))

        self.scene.media_path.delete(save=False)

        self.assertFalse(self.storage.exists(name))
        self.assertFalse(self.storage.exists(thumb))

    def test_serializer_includes_thumbnails(self):
        storage_provider.upload(self.scene.media_path, _img_tmp(), save=True)
        data = SceneSerializer(self.scene).data
        self.assertIn("thumbnails", data)
        self.assertEqual(set(data["thumbnails"]), set(SIZES))
