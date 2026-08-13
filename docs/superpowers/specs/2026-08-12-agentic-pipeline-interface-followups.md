# Agentic Pipeline Interface — Follow-ups

Found while building phase 1
(`2026-08-12-agentic-pipeline-interface-design.md`). Each was deliberately left
out of that branch to keep it scoped to the agent interface. None are caused by
it.

## 1. `make test` runs a third of the pipeline tests

`make test` runs the Django app tests, then only `tests/test_pipeline_isolation.py`
and `tests/test_registry.py`, then `tests/test_expand.py`. It does not run
`test_animate_flag.py`, `test_image_provider_selection.py`, or `test_styles.py` —
all of which pass today and are simply never executed by CI or by anyone typing
`make test`.

## 2. `tests/test_voiceover_helpers.py` runs under nothing

It is a Django `TestCase` living in `tests/`, so:

- `pytest` cannot configure it → `ImproperlyConfigured: Requested setting DATABASES`
- `manage.py test apps` does not discover it (it only walks `backend/apps/`)

Measured:

| Command | Result |
|---|---|
| `uv run python -m pytest tests/` | 42 passed, 7 errors |
| `DJANGO_SETTINGS_MODULE=config.settings.test PYTHONPATH=backend uv run python -m pytest tests/` | 48 passed, **1 failed** |

So six of the seven errors are configuration. The remaining one is a real
failure nobody can currently see:
`test_generate_voiceover_rejects_invalid_scene_indices` —
`ValidationError` at `tests/test_voiceover_helpers.py:93`.

Fixing 1 and 2 together means widening the `test` target and deciding where
Django-dependent pipeline tests should live.

## 3. Two pre-existing Django test failures

`backend/apps/projects/tests/test_tasks_plan.py` —
`RunPlanStageTest.test_happy_path` and `RunRefineStageTest.test_happy_path`,
both `AssertionError: 'FAILED' != Status.REVIEW`.

Verified pre-existing: both reproduce identically on `main` at `ad2dba0`.
`make test` currently exits non-zero because of them.

## 4. `pipeline.voiceover` has no `--scene` flag

`generate_voiceover()` accepts `scene_indices`, but the CLI
(`pipeline/voiceover.py:141-158`) exposes only `work_dir` and `--voice`. So a
single failed scene cannot be retried through the documented stage command, and
re-running regenerates every scene — shifting caption timings on scenes that
were fine.

`pipeline.images` already has `--scene N` (`pipeline/images/__main__.py:22`).
Adding the matching flag to voiceover would remove the `python -c` carve-out
that `voiceover-director` currently has to document as an exception to Rule Zero.

## 5. `latest_work_dir()` defaulting is fragile

Every stage command defaults to the most recently touched `output/*/` folder.
The repo currently has ~27 of them. With more than one video in flight, "most
recently touched" is easy to get wrong and there is no confirmation prompt.

Raised by the behavioral-test agent while rehearsing a real run.

## 6. Deferred minors from the final review

Triaged as acceptable to defer, recorded so they are not lost:

- `probe_llm` catches only `RuntimeError` from `default_model()` — tight coupling,
  though `preflight()`'s per-probe guard now covers the general case.
- `_ffmpeg_filters`' real subprocess path has no test; every test monkeypatches
  it. (It was exercised live during verification and works.)
- `render_table`'s column widths are hardcoded (`<15`, `<18`). A long
  `LITELLM_MODEL` id would misalign the table — no truncation, just cosmetics.
- `test_main_loads_env_before_probing` proves `load_env()` is called, not that it
  precedes the probes. Ordering is currently guaranteed by code structure only.
- `.env.example` styling: 4 of the 7 added vars are uncommented while 3 are
  commented, though the section header says "all optional".
- `plan-director`'s "What good looks like" restates `shot-plan`'s character and
  negative-prompt rules rather than linking down. Verified accurate; duplication
  is a maintenance cost, not a correctness one.
