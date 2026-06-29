from apps.projects.choices import Status

TRANSITIONS: dict[str, set[str]] = {
    Status.DRAFT: {Status.PLANNING},
    Status.PLANNING: {Status.REVIEW, Status.FAILED},
    Status.REVIEW: {Status.PLANNING, Status.GENERATING},
    Status.GENERATING: {Status.DONE, Status.FAILED},
    Status.FAILED: {Status.GENERATING},
    Status.DONE: {Status.VIDEO_GENERATING},
    Status.VIDEO_GENERATING: {Status.DONE},
}
