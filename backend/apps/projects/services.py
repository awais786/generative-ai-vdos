import json
import logging
import threading

from django.conf import settings
from django.db import transaction

from apps.accounts.models import UserProfile
from apps.projects.constants import Level, Stage
from apps.projects.models import JobLog, Project

logger = logging.getLogger(__name__)

_redis_pool = None
_redis_lock = threading.Lock()


def _get_redis():
    """Return a Redis client from the shared pool, or None when unavailable."""
    global _redis_pool

    # Fast path (no lock): pool already initialised.
    if _redis_pool is not None:
        import redis
        return redis.Redis(connection_pool=_redis_pool)

    broker_url = getattr(settings, "CELERY_BROKER_URL", None)
    if not broker_url:
        return None

    try:
        import redis
    except ImportError:
        logger.warning("redis package not installed — publish_event will log only")
        return None

    # Slow path: acquire lock and double-check before creating the pool.
    with _redis_lock:
        if _redis_pool is not None:
            return redis.Redis(connection_pool=_redis_pool)
        try:
            pool = redis.ConnectionPool.from_url(broker_url)
            client = redis.Redis(connection_pool=pool)
            client.ping()
            _redis_pool = pool
            return client
        except Exception:
            logger.warning("Redis unavailable — publish_event will log only")
            return None


def publish_event(project_id, stage, level, message, **extra):
    """Persist event to JobLog and optionally broadcast via Redis pub/sub."""
    JobLog.objects.create(
        project_id=project_id, stage=stage, level=level, message=message,
    )

    client = _get_redis()
    if client is None:
        return

    payload = json.dumps({
        "project_id": str(project_id),
        "stage": stage,
        "level": level,
        "message": message,
        **extra,
    }, default=str)
    try:
        client.publish(f"project:{project_id}:events", payload)
    except Exception:
        logger.warning("Redis publish failed for project %s", project_id)


class ProjectService:
    @staticmethod
    @transaction.atomic
    def create(owner: UserProfile, prompt: str, **kwargs) -> Project:
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
    """In eager (dev) mode run fn in a daemon thread so the HTTP response returns first."""
    from django.conf import settings
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        import threading
        threading.Thread(target=fn, args=args, daemon=True).start()
    else:
        fn(*args)


def _dispatch_plan_stage(project_id: str) -> None:
    from .tasks import run_plan_stage
    _eager_thread(run_plan_stage.delay, project_id)
