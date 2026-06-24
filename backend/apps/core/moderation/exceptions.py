class ContentPolicyViolation(Exception):
    """Raised when user-supplied text fails content moderation."""

    default_message = (
        "This content isn't allowed. Please remove offensive language and try again."
    )

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)
