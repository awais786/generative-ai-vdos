"""
Verifies that upload_to helpers produce the expected key structure so that
S3 objects land in the correct user-scoped prefix.
"""
import tempfile
from pathlib import Path

from django.test import TestCase

from apps.accounts.models import UserProfile
from apps.projects.models import Project, Scene
from apps.storage import storage_provider


def _owner(sub="sub-paths"):
    return UserProfile.objects.create(cognito_sub=sub, email=f"{sub}@test.com")


def _project(owner):
    return Project.objects.create(owner=owner, prompt="paths test")


def _tmp(suffix=".png") -> Path:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(b"data")
        f.flush()
        return Path(f.name)


class UploadToPathStructureTest(TestCase):
    """Storage keys match {owner_id}/{project_id}/{sub-folder}/{filename}."""

    def setUp(self):
        self.owner = _owner()
        self.project = _project(self.owner)
        self.scene = Scene.objects.create(project=self.project, index=0)

    def test_scene_media_path_structure(self):
        storage_provider.upload(self.scene.media_path, _tmp(".png"))
        self.scene.refresh_from_db()
        key = self.scene.media_path.name
        self.assertTrue(key.startswith(f"{self.owner.id}/{self.project.id}/images/"), key)

    def test_different_users_have_different_prefixes(self):
        owner2 = UserProfile.objects.create(cognito_sub="sub-paths-2", email="sub-paths-2@test.com")
        project2 = _project(owner2)
        scene2 = Scene.objects.create(project=project2, index=0)

        storage_provider.upload(self.scene.media_path, _tmp(".png"))
        storage_provider.upload(scene2.media_path, _tmp(".png"))

        self.scene.refresh_from_db()
        scene2.refresh_from_db()

        prefix1 = self.scene.media_path.name.split("/")[0]
        prefix2 = scene2.media_path.name.split("/")[0]
        self.assertNotEqual(prefix1, prefix2)

    def test_different_projects_have_different_prefixes(self):
        project2 = _project(self.owner)
        scene2 = Scene.objects.create(project=project2, index=0)

        storage_provider.upload(self.scene.media_path, _tmp(".png"))
        storage_provider.upload(scene2.media_path, _tmp(".png"))

        self.scene.refresh_from_db()
        scene2.refresh_from_db()

        # Same owner prefix, different project segment
        self.assertEqual(
            self.scene.media_path.name.split("/")[0],
            scene2.media_path.name.split("/")[0],
        )
        self.assertNotEqual(
            self.scene.media_path.name.split("/")[1],
            scene2.media_path.name.split("/")[1],
        )
