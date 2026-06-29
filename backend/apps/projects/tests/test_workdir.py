from django.core.files.base import ContentFile
from django.test import TestCase

from apps.accounts.models import UserProfile
from apps.projects.models import Project, Scene
from apps.projects.workdir import materialize_work_dir


def make_user(sub="workdir-user"):
    return UserProfile.objects.create(cognito_sub=sub, email=f"{sub}@example.com")


class MaterializeWorkDirTest(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = Project.objects.create(
            owner=self.owner,
            prompt="test",
            shot_plan={"title": "Test", "music_mood": "calm"},
        )

    def _scene_with_assets(self, **kwargs):
        scene = Scene.objects.create(
            project=self.project, index=0, narration="n", media_prompt="m", **kwargs,
        )
        scene.media_path.save("scene_00.png", ContentFile(b"\x89PNG"), save=True)
        scene.audio_path.save("scene_00.mp3", ContentFile(b"ID3"), save=True)
        return scene

    def test_png_goes_to_images_dir(self):
        self._scene_with_assets()

        work_dir, _ = materialize_work_dir(self.project)
        self.assertTrue((work_dir / "images" / "scene_00.png").is_file())
        self.assertFalse((work_dir / "video" / "scene_00.mp4").exists())

    def test_mp4_goes_to_video_dir(self):
        scene = Scene.objects.create(
            project=self.project, index=0, narration="n", media_prompt="m", animate=True,
        )
        scene.media_path.save("scene_00.mp4", ContentFile(b"fake-mp4"), save=True)
        scene.audio_path.save("scene_00.mp3", ContentFile(b"ID3"), save=True)

        work_dir, _ = materialize_work_dir(self.project)
        self.assertTrue((work_dir / "video" / "scene_00.mp4").is_file())
        self.assertFalse((work_dir / "images" / "scene_00.png").exists())

    def test_missing_audio_raises(self):
        scene = Scene.objects.create(
            project=self.project, index=0, narration="n", media_prompt="m",
        )
        scene.media_path.save("scene_00.png", ContentFile(b"\x89PNG"), save=True)

        with self.assertRaises(FileNotFoundError):
            materialize_work_dir(self.project)
