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
