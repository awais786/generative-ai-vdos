"""What each stage discloses before it works.

Part 1 (the bug this fixes): a plan whose music_mood has no matching folder used
to score the video with a random track from an unrelated mood and print only the
chosen path — indistinguishable from success. The choice must now be reportable.

Part 2: every stage states what it will use, where that came from, and whether it
costs money, on short single lines (the web app captures them as job logs).
"""
from pathlib import Path

import pytest

from pipeline import report
from pipeline.assemble import choose_music, music_report, pick_music
from pipeline.schema import Scene, ShotPlan


def make_music_tree(root, folders):
    for name, tracks in folders.items():
        d = root / name
        d.mkdir(parents=True)
        for t in tracks:
            (d / t).write_bytes(b"")


def make_plan(**kw):
    defaults = dict(
        title="t", description="d", tags=["a"], music_mood="calm",
        style_prefix="cinematic photo",
        scenes=[Scene(narration="one", media_prompt="a hill"),
                Scene(narration="two", media_prompt="a valley")],
    )
    return ShotPlan(**{**defaults, **kw})


# ---------------------------------------------------------------- part 1: music

def test_choose_music_reports_a_real_mood_match(tmp_path):
    make_music_tree(tmp_path, {"calm": ["a.mp3"], "theft": ["b.mp3"]})
    choice = choose_music(tmp_path, "calm")
    assert choice.matched is True
    assert choice.path == tmp_path / "calm" / "a.mp3"
    assert choice.source == "mood"


def test_choose_music_reports_a_random_fallback_when_the_mood_folder_is_missing(tmp_path):
    make_music_tree(tmp_path, {"theft": ["robbery.mp3"]})
    choice = choose_music(tmp_path, "inspiring")
    # Fallback behaviour is kept — some music beats no music.
    assert choice.path == tmp_path / "theft" / "robbery.mp3"
    # ...but the caller can now tell it apart from a real match.
    assert choice.matched is False
    assert choice.source == "fallback"
    assert choice.mood == "inspiring"
    assert choice.mood_dir_exists is False
    assert choice.moods_available == ("theft",)


def test_choose_music_reports_a_fallback_when_the_mood_folder_is_empty(tmp_path):
    make_music_tree(tmp_path, {"inspiring": [], "calm": ["a.mp3"]})
    choice = choose_music(tmp_path, "inspiring")
    assert choice.matched is False
    assert choice.mood_dir_exists is True
    assert choice.moods_available == ("calm",)


def test_choose_music_reports_nothing_available(tmp_path):
    choice = choose_music(tmp_path / "missing", "calm")
    assert choice.path is None
    assert choice.source == "none"
    assert choice.matched is False


def test_pick_music_keeps_returning_a_path_for_existing_callers(tmp_path):
    make_music_tree(tmp_path, {"calm": ["a.mp3"]})
    assert pick_music(tmp_path, "calm") == tmp_path / "calm" / "a.mp3"
    assert pick_music(tmp_path / "missing", "calm") is None


def test_music_report_warns_naming_the_missing_folder_and_the_moods_that_exist(
        tmp_path, monkeypatch):
    # Relative root, exactly as the CLIs use it (--music-dir defaults to "music").
    monkeypatch.chdir(tmp_path)
    make_music_tree(tmp_path / "music",
                    {"calm": [], "theft": ["robbery.mp3"], "upbeat": ["u.mp3"]})
    # A mood with no folder AND no alias — "inspiring" now resolves to upbeat,
    # which is the point of MOOD_ALIASES; this test is about the case that
    # genuinely cannot be matched.
    lines = music_report(choose_music(Path("music"), "klezmer"))
    text = "\n".join(lines)
    warnings = [ln for ln in lines if ln.startswith("warning")]
    assert warnings, f"a random-mood fallback must warn, got:\n{text}"
    assert "no music/klezmer/ folder" in text           # names the missing folder
    assert "theft, upbeat" in text                       # lists the moods that do exist
    assert "calm" not in text.split("moods available")[1]  # empty folder is not a mood
    # ...and still says what it actually picked (a random one of the two moods).
    assert any(t in lines[0] for t in ("theft/robbery.mp3", "upbeat/u.mp3"))


def test_music_warning_stays_in_budget_with_a_long_absolute_music_root(tmp_path):
    root = tmp_path / "a-very-deeply-nested" / "working-directory" / "music"
    make_music_tree(root, {"theft": ["robbery.mp3"]})
    lines = music_report(choose_music(root, "inspiring"))
    for ln in lines:
        assert len(ln) <= report.MAX_LINE, f"{len(ln)} chars: {ln}"
    warn = next(ln for ln in lines if ln.startswith("warning"))
    # The path is elided from the left, so the part that names the folder lives.
    assert "/inspiring/ folder" in warn


def test_music_report_stays_quiet_on_a_real_match(tmp_path):
    make_music_tree(tmp_path, {"calm": ["a.mp3"]})
    lines = music_report(choose_music(tmp_path, "calm"))
    assert not [ln for ln in lines if ln.startswith("warning")]
    assert "calm/a.mp3" in lines[0]


def test_music_report_says_none_when_there_are_no_tracks(tmp_path):
    lines = music_report(choose_music(tmp_path, "calm"))
    assert "none" in lines[0]


# ------------------------------------------------------------- part 2: headers

def test_row_is_a_single_plain_line():
    line = report.row("plan", "gpt-4o-mini", "via LLM_PROVIDER=openai")
    assert "\n" not in line and "\x1b" not in line
    assert line.startswith("plan")
    assert "gpt-4o-mini" in line and "LLM_PROVIDER=openai" in line


def test_warning_lines_are_labelled_so_logs_are_greppable():
    assert report.warning("no music/inspiring/").startswith("warning")


def test_plan_report_names_the_model_provider_and_cost(monkeypatch):
    from pipeline.script_agent import plan_report

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    text = "\n".join(plan_report("gpt-4o-mini"))
    assert "gpt-4o-mini" in text
    assert "LLM_PROVIDER=openai" in text
    assert "$" in text  # states that it costs money


def test_plan_report_says_when_the_model_was_forced(monkeypatch):
    from pipeline.script_agent import plan_report

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert "--model" in "\n".join(plan_report("gpt-5", forced=True))


def test_images_report_names_the_backend_its_key_and_its_cost(monkeypatch):
    """This used to assert the banner called qwen "free". Model Studio's free
    developer quota ended in April 2026 and qwen now bills ~$0.025/image, so
    the assertion was pinning a claim that had stopped being true. The banner
    must state a cost; it must not promise $0."""
    import pipeline.images as images

    qwen = next(p for p in images.PROVIDERS if p.name == "qwen-image")
    text = "\n".join(images.selection_report(qwen, forced=False, scenes=4))
    assert "qwen-image" in text
    assert "DASHSCOPE_API_KEY" in text
    assert "0.025" in text, "the banner must name the real per-image cost"
    assert "4 scenes" in text


def test_images_report_marks_the_paid_backend(monkeypatch):
    import pipeline.images as images

    gpt = next(p for p in images.PROVIDERS if p.name == "gpt-image-1")
    text = "\n".join(images.selection_report(gpt, forced=True, scenes=1))
    assert "PAID" in text
    assert "--backend" in text  # a forced pick says so instead of listing skips


def test_images_report_says_which_free_backends_were_skipped_and_why(monkeypatch):
    import pipeline.images as images

    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", (lambda: True) if p.name == "placeholder"
                            else (lambda: False))
    placeholder = next(p for p in images.PROVIDERS if p.name == "placeholder")
    lines = images.selection_report(placeholder, forced=False, scenes=2)
    text = "\n".join(lines)
    assert "qwen-image skipped" in text
    assert "DASHSCOPE_API_KEY" in text
    assert all("\n" not in ln for ln in lines)


def test_voice_report_names_the_voice_and_that_edge_tts_is_free():
    from pipeline.voiceover import voice_report

    text = "\n".join(voice_report(make_plan(), "en-US-AndrewNeural"))
    assert "en-US-AndrewNeural" in text
    assert "edge-tts" in text and "free" in text
    assert "2 scenes" in text


def test_voice_report_mentions_per_scene_voices():
    from pipeline.voiceover import voice_report

    plan = make_plan(scenes=[
        Scene(narration="one", media_prompt="a", voice="ur-PK-UzmaNeural"),
        Scene(narration="two", media_prompt="b"),
    ])
    text = "\n".join(voice_report(plan, "en-US-AndrewNeural"))
    assert "ur-PK-UzmaNeural" in text


# What OpenAI actually returns when it refuses a prompt — the realistic worst
# case for the note lines that fire on a failure, and the reason a line cap has
# to apply to the whole assembled line, not just the error fragment.
MODERATION_ERROR = RuntimeError(
    "Error code: 400 - {'error': {'code': 'moderation_blocked', 'message': "
    "'Your request was rejected as a result of our safety system. Your prompt "
    "may contain text that is not allowed by our safety system.', 'param': None, "
    "'type': 'invalid_request_error'}}"
)


class FailingEditProvider:
    """A provider whose reference edit and generate both fail loudly."""

    name = "fake-provider"
    requires = "FAKE_API_KEY"
    can_edit = True   # this double exists to exercise the failing-edit path

    def available(self):
        return True

    def generate(self, prompt, query=None, negative=None, api_key=None,
                 model=None, on_preview_url=None):
        raise MODERATION_ERROR

    def edit(self, prompt, refs, negative=None, api_key=None, model=None,
             on_preview_url=None):
        raise MODERATION_ERROR


def image_failure_lines(tmp_path, monkeypatch, capsys):
    """Every line the images stage prints when a real provider refuses."""
    import pipeline.images as images

    for p in images.PROVIDERS:
        monkeypatch.setattr(p, "available", (lambda: True) if p.name == "placeholder"
                            else (lambda: False))
    plan = make_plan(
        characters=[{"name": "pip", "description": "a small brown sparrow"}],
        scenes=[Scene(narration="one", media_prompt="{pip} on a hill")],
    )
    primary = FailingEditProvider()
    ref = tmp_path / "pip.png"
    ref.write_bytes(b"")
    capsys.readouterr()
    # Reference portraits: provider.generate refuses.
    images.character_refs(plan, primary, tmp_path / "out")
    # Reference edit refused -> text-to-image, then the whole chain refuses too.
    images.generate_scene_image(plan, 0, primary, fallback=True,
                                char_refs={"pip": ref})
    return [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]


def test_image_failure_notes_stay_within_the_line_budget(tmp_path, monkeypatch, capsys):
    lines = image_failure_lines(tmp_path, monkeypatch, capsys)
    assert any("reference edit" in ln for ln in lines), lines
    assert any("fake-provider" in ln for ln in lines), lines
    for ln in lines:
        assert len(ln) <= report.MAX_LINE, f"{len(ln)} chars: {ln}"
        assert "\n" not in ln and "\x1b" not in ln


def test_image_failure_notes_keep_the_authored_half_when_truncated(
        tmp_path, monkeypatch, capsys):
    # Truncation must eat the provider's error text, never the sentence that
    # says what the pipeline did about it.
    lines = image_failure_lines(tmp_path, monkeypatch, capsys)
    edit_note = next(ln for ln in lines if "reference edit" in ln)
    assert "text-to-image instead" in edit_note


@pytest.mark.parametrize("builder", ["music", "voice"])
def test_every_reported_line_is_short_and_single_line(tmp_path, monkeypatch, builder):
    from pipeline.voiceover import voice_report

    # Relative music root, as the CLIs use it (--music-dir defaults to "music").
    monkeypatch.chdir(tmp_path)
    make_music_tree(tmp_path / "music", {"theft": ["4379051-robbery-205343.mp3"]})
    lines = (music_report(choose_music(Path("music"), "inspiring")) if builder == "music"
             else voice_report(make_plan(), "en-US-AndrewNeural"))
    for ln in lines:
        assert "\n" not in ln
        assert "\x1b" not in ln
        assert len(ln) <= 120, ln


def test_an_aliased_mood_does_not_warn(tmp_path, monkeypatch):
    """`inspiring` was the most common mood in the corpus and had no folder, so
    every one of those videos warned and drew a random track. Resolved through
    MOOD_ALIASES it is a real match, and a real match must be quiet."""
    monkeypatch.chdir(tmp_path)
    make_music_tree(tmp_path / "music", {"upbeat": ["u.mp3"], "sad": ["s.mp3"]})
    lines = music_report(choose_music(Path("music"), "inspiring"))
    assert not [ln for ln in lines if ln.startswith("warning")], "\n".join(lines)
    assert "upbeat/u.mp3" in lines[0]
