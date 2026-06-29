from django.test import SimpleTestCase

from pipeline.voiceover import normalize_tts_text, resolve_voice


class VoiceoverHelpersTest(SimpleTestCase):
    def test_normalize_smart_quotes(self):
        text = normalize_tts_text("It\u2019s a test.")
        self.assertEqual(text, "It's a test.")

    def test_resolve_voice_falls_back_for_invalid(self):
        self.assertEqual(
            resolve_voice("not-a-voice", "en-US-AvaNeural"),
            "en-US-AvaNeural",
        )

    def test_resolve_voice_keeps_valid_per_scene_voice(self):
        self.assertEqual(
            resolve_voice("en-US-RyanNeural", "en-US-AndrewNeural"),
            "en-US-RyanNeural",
        )

    def test_synth_scene_with_retry_rejects_zero_attempts(self):
        import asyncio
        from pipeline.voiceover import synth_scene_with_retry
        from pathlib import Path
        import tempfile

        async def run():
            with tempfile.TemporaryDirectory() as tmpdir:
                mp3 = Path(tmpdir) / "a.mp3"
                words = Path(tmpdir) / "a.words.json"
                with self.assertRaises(RuntimeError) as ctx:
                    await synth_scene_with_retry("hello", "en-US-AndrewNeural", mp3, words, max_attempts=0)
                self.assertIn("max_attempts", str(ctx.exception))

        asyncio.run(run())

    def test_synth_scene_with_retry_recovers_after_transient_failure(self):
        import asyncio
        from pathlib import Path
        import tempfile
        from unittest.mock import AsyncMock, patch

        from edge_tts.exceptions import NoAudioReceived
        from pipeline.voiceover import synth_scene_with_retry

        async def run():
            with tempfile.TemporaryDirectory() as tmpdir:
                mp3 = Path(tmpdir) / "a.mp3"
                words = Path(tmpdir) / "a.words.json"
                mock_synth = AsyncMock(
                    side_effect=[NoAudioReceived("empty"), None],
                )
                with patch("pipeline.voiceover.synth_scene", mock_synth):
                    with patch("pipeline.voiceover.asyncio.sleep", AsyncMock()):
                        await synth_scene_with_retry(
                            "hello", "en-US-AndrewNeural", mp3, words, max_attempts=2,
                        )
                self.assertEqual(mock_synth.await_count, 2)

        asyncio.run(run())

    def test_synth_scene_with_retry_rethrows_after_exhausted_attempts(self):
        import asyncio
        from pathlib import Path
        import tempfile
        from unittest.mock import AsyncMock, patch

        from edge_tts.exceptions import NoAudioReceived
        from pipeline.voiceover import synth_scene_with_retry

        async def run():
            with tempfile.TemporaryDirectory() as tmpdir:
                mp3 = Path(tmpdir) / "a.mp3"
                words = Path(tmpdir) / "a.words.json"
                mock_synth = AsyncMock(side_effect=NoAudioReceived("empty"))
                with patch("pipeline.voiceover.synth_scene", mock_synth):
                    with patch("pipeline.voiceover.asyncio.sleep", AsyncMock()):
                        with self.assertRaises(NoAudioReceived):
                            await synth_scene_with_retry(
                                "hello", "en-US-AndrewNeural", mp3, words, max_attempts=2,
                            )

        asyncio.run(run())

    def test_generate_voiceover_rejects_invalid_scene_indices(self):
        from pipeline.schema import ShotPlan
        from pipeline.voiceover import generate_voiceover
        from pathlib import Path
        import tempfile

        plan = ShotPlan.model_validate({
            "title": "Test",
            "scenes": [{"media_prompt": "a", "narration": "hello"}],
        })
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                generate_voiceover(plan, Path(tmpdir), scene_indices=[-1])
