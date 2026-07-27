from apps.projects.choices import Status

PROJECT_THROTTLE_SCOPES: dict[str, str] = {
    "create": "throttle_plan",
    "refine": "throttle_plan",
    "approve": "throttle_images",
    "approve_images": "throttle_images",
    "retry": "throttle_images",
    "regenerate_images": "throttle_images",
    "regenerate_voiceovers": "throttle_voice",
}

SCENE_THROTTLE_SCOPES: dict[str, str] = {
    "regenerate": "throttle_images",
    "revoice": "throttle_voice",
}

TRANSITIONS: dict[str, set[str]] = {
    Status.DRAFT: {Status.PLANNING},
    Status.PLANNING: {Status.REVIEW, Status.FAILED},
    Status.REFINING: {Status.REVIEW, Status.FAILED},
    Status.REVIEW: {Status.REFINING, Status.GENERATING},
    Status.GENERATING: {Status.IMAGE_REVIEW, Status.VIDEO_GENERATING, Status.DONE, Status.FAILED},
    Status.IMAGE_REVIEW: {Status.VIDEO_GENERATING, Status.FAILED},
    Status.FAILED: {Status.GENERATING, Status.REVIEW},
    Status.DONE: {Status.VIDEO_GENERATING},
    Status.VIDEO_GENERATING: {Status.DONE, Status.FAILED},
}
