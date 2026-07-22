import logging
import threading
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from rest_framework.exceptions import APIException

from apps.accounts.models import UserProfile
from apps.projects.choices import Level, Stage
from apps.projects.models import JobLog, Project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate / budget enforcement
# ---------------------------------------------------------------------------

class GenerationBudgetExceeded(APIException):
    """Raised when a user has hit their daily generation cap.

    DRF's exception handler maps this to HTTP 429 automatically.
    ``self.wait`` carries seconds until the budget resets (UTC midnight),
    which callers can surface as a ``Retry-After`` header.
    """
    status_code = 429
    default_code = "budget_exceeded"
    default_detail = "Daily generation limit reached. Resets at 00:00 UTC."

    def __init__(self, retry_after_seconds: int):
        super().__init__()
        self.wait = retry_after_seconds


def _seconds_until_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(int((midnight - now).total_seconds()), 1)


def enforce_daily_budget(owner: UserProfile) -> None:
    """Increment and check the user's daily generation counter.

    Raises GenerationBudgetExceeded if the cap is exceeded.
    Call this before any paid-provider dispatch in the view layer.

    Counter key: ``generation_count:<cognito_sub>:<YYYY-MM-DD>`` (UTC).
    Expires at UTC midnight. One increment = one paid dispatch.

    Do NOT count JobLog rows — a message rename would silently break the
    budget. Do NOT put this check inside on_commit callbacks — the HTTP
    response would already be sent before the exception could propagate.
    """
    cap = getattr(settings, "MAX_GENERATIONS_PER_DAY", 20)
    today = datetime.now(timezone.utc).date().isoformat()
    key = f"generation_count:{owner.cognito_sub}:{today}"
    ttl = _seconds_until_utc_midnight()

    # cache.incr() raises ValueError on a missing key in Django's Redis
    # backend. Seed with add() first (no-op if key exists, safe under
    # concurrent requests). Retry once to handle the key-expiry race between
    # add() and incr().
    cache.add(key, 0, timeout=ttl)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.add(key, 0, timeout=ttl)
        count = cache.incr(key)

    if count > cap:
        raise GenerationBudgetExceeded(retry_after_seconds=ttl)


# ---------------------------------------------------------------------------
# Redis pub/sub removed — progress is served via /logs/?after= polling.
# publish_event now only persists to JobLog.
# ---------------------------------------------------------------------------

def publish_event(project_id, stage, level, message, **extra):
    """Persist event to JobLog."""
    JobLog.objects.create(
        project_id=project_id, stage=stage, level=level, message=message,
    )


class ProjectService:
    @staticmethod
    @transaction.atomic
    def create(owner: UserProfile, prompt: str, **kwargs) -> Project:
        enforce_daily_budget(owner)
        project = Project.objects.create(owner=owner, prompt=prompt, **kwargs)
        JobLog.objects.create(
            project=project,
            stage=Stage.PLAN,
            level=Level.INFO,
            message="Project created.",
        )
        transaction.on_commit(
            lambda: _dispatch_plan_stage(str(project.id))
        )
        return project


def _eager_thread(fn, *args) -> None:
    """Run fn(*args) in a daemon thread when CELERY_TASK_ALWAYS_EAGER is set.

    In development/test (ALWAYS_EAGER=True) this lets the HTTP response return
    before the task runs. In deployment (ALWAYS_EAGER=False, real worker) the
    daemon-thread branch is unreachable — fn(*args) is .delay(), which enqueues
    and returns immediately without blocking.
    """
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        from django.db import close_old_connections

        def _run():
            try:
                fn(*args)
            finally:
                # Daemon threads hold their own thread-local DB connection.
                # Release it so SQLite isn't locked until interpreter exit.
                close_old_connections()

        threading.Thread(target=_run, daemon=True).start()
    else:
        fn(*args)


def _dispatch_plan_stage(project_id: str) -> None:
    from .tasks import run_plan_stage
    _eager_thread(run_plan_stage.delay, project_id)
