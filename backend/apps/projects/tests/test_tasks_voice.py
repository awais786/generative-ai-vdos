from io import BytesIO
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase

from apps.accounts.models import UserProfile
from apps.projects.choices import Status, VoiceStatus
from apps.projects.models import Project, Scene
from apps.projects.tasks import run_assemble_stage, run_voice_stage


def make_user(sub="voice-user"):
    return UserProfile.objects.create(cognito_sub=sub, email=f"{sub}@example.com")


class RunVoiceStageTest(TestCase):
    def setUp(self):
        self.owner = make_user()
        self.project = Project.objects.create(
            owner=self.owner,
            prompt="berries",
            status=Status.GENERATING,
            shot_plan={
                "title": "Berries",
                "description": "A story",
                "tags": ["berries"],
                "music_mood": "calm",
                "style_prefix": "cinematic",
            },
            narrator_voice="en-US-AndrewNeural",
        )
        self.scene = Scene.objects.create(
            project=self.project,
            index=0,
            narration="Once upon a time.",
            media_prompt="berries on a table",
        )

    @patch("apps.projects.utils.generate_voiceover")
    @patch("apps.projects.utils._upload_voice_files")
    def test_generates_all_scenes(self, mock_upload, mock_gen):
        def fake_gen(plan, out_dir, voice=None, scene_indices=None):
            out_dir.mkdir(parents=True, exist_ok=True)
            mp3 = out_dir / "scene_00.mp3"
            mp3.write_bytes(b"ID3")
            (out_dir / "scene_00.words.json").write_text("[]")
            return [mp3]

        mock_gen.side_effect = fake_gen
        run_voice_stage(str(self.project.id))

        mock_gen.assert_called_once()
        self.assertTrue(mock_upload.called)

    @patch("apps.projects.utils.synth_scene_sync")
    def test_single_scene_revoice(self, mock_synth):
        def fake_synth(text, voice, mp3_path, words_path):
            mp3_path.write_bytes(b"ID3")
            words_path.write_text("[]")

        mock_synth.side_effect = fake_synth
        self.project.status = Status.DONE
        self.project.save(update_fields=["status", "updated_at"])

        run_voice_stage(str(self.project.id), scene_index=0)

        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Status.DONE)
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.voice_status, VoiceStatus.DONE)

    @patch("apps.projects.utils.synth_scene_sync")
    def test_invalid_scene_voice_falls_back_to_narrator(self, mock_synth):
        captured = {}

        def fake_synth(text, voice, mp3_path, words_path):
            captured["voice"] = voice
            mp3_path.write_bytes(b"ID3")
            words_path.write_text("[]")

        mock_synth.side_effect = fake_synth
        self.scene.voice = "not-a-voice"
        self.scene.save(update_fields=["voice", "updated_at"])
        self.project.status = Status.DONE
        self.project.save(update_fields=["status", "updated_at"])

        run_voice_stage(str(self.project.id), scene_index=0)

        self.assertEqual(captured["voice"], "en-US-AndrewNeural")

    @patch("apps.projects.utils.generate_voiceover", side_effect=RuntimeError("boom"))
    def test_batch_failure_marks_scenes_failed(self, _mock_gen):
        self.scene.voice_status = VoiceStatus.PENDING
        self.scene.save(update_fields=["voice_status", "updated_at"])
        self.project.status = Status.DONE
        self.project.save(update_fields=["status", "updated_at"])

        with self.assertRaises(RuntimeError):
            run_voice_stage(str(self.project.id))

        self.scene.refresh_from_db()
        self.assertEqual(self.scene.voice_status, VoiceStatus.FAILED)


class RunAssembleStageTest(TestCase):
    def setUp(self):
        self.owner = make_user("assemble-user")
        self.project = Project.objects.create(
            owner=self.owner,
            prompt="berries",
            status=Status.GENERATING,
            shot_plan={
                "title": "Berries",
                "description": "A story",
                "tags": ["berries"],
                "music_mood": "calm",
                "style_prefix": "cinematic",
            },
        )
        self.scene = Scene.objects.create(
            project=self.project,
            index=0,
            narration="Hello world.",
            media_prompt="berries",
            voice_status=VoiceStatus.DONE,
        )
        png = BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        self.scene.media_path.save("scene_00.png", ContentFile(png.getvalue()), save=True)
        self.scene.audio_path.save("scene_00.mp3", ContentFile(b"ID3"), save=True)
        self.scene.words_path.save(
            "scene_00.words.json",
            ContentFile(b'[{"text":"Hello","start":0.0,"duration":0.5}]'),
            save=True,
        )

    @patch("apps.projects.tasks.assemble")
    @patch("apps.projects.tasks.pick_music", return_value=None)
    def test_assemble_uploads_final_video(self, _pick, mock_assemble):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"fake-mp4")
            final_path = Path(tmp.name)

        mock_assemble.return_value = final_path
        run_assemble_stage(str(self.project.id))

        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Status.DONE)
        self.assertFalse(self.project.stale)
        self.assertTrue(self.project.final_video_path)

        final_path.unlink(missing_ok=True)
