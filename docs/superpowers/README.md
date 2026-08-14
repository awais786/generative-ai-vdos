# Design records

## `specs/` — kept

Why a decision was made, and what was rejected. This is the part that is **not
recoverable from the code**: `2026-08-13-text-layer-redundancy-design.md` is the
only place that says why `_covers()` needs a 0.6 coverage threshold rather than
plain containment, and what the corpus measurement was that ruled the simpler
rule out.

Several carry a **Correction** block added after implementation or review, where
the built thing diverged from the design. Those are deliberate: a spec that
quietly disagrees with the code is worse than no spec.

## `plans/` — removed, deliberately

Step-by-step implementation plans used to live here. Fifteen of them, 11,243
lines — more than `pipeline/` and the Django backend combined, and 73% of all
prose in the repo.

They were single-use by construction. The `writing-plans` skill requires full
code blocks so an engineer with no context can follow along, so each plan is a
transcription of code that now exists for real. Every one described work that
had already shipped. Nothing read them again.

They remain in git history if a decision ever needs archaeology.

**Going forward:** write the spec, skip the plan document when the work is being
implemented in the same session by whoever designed it. A plan earns its length
only when it is handed to someone — or something — that was not part of the
design conversation.
