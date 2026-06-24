from rest_framework import serializers
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST

from .exceptions import ContentPolicyViolation
from .service import check_text

POLICY_MESSAGE = ContentPolicyViolation.default_message


class ContentPolicyAPIException(APIException):
    status_code = HTTP_400_BAD_REQUEST
    default_detail = POLICY_MESSAGE
    default_code = "content_policy"


def raise_moderation_error() -> None:
    raise ContentPolicyAPIException()


def validate_user_text(value):
    """Check a single string; raises ContentPolicyAPIException on block."""
    if value in (None, ""):
        return value
    try:
        check_text(value)
    except ContentPolicyViolation:
        raise_moderation_error()
    return value


class ModeratedFieldsMixin:
    """Serializer mixin — set ``moderated_fields`` to the text fields to scan."""

    moderated_fields: tuple[str, ...] = ()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        for name in self.moderated_fields:
            value = attrs.get(name)
            if value not in (None, ""):
                validate_user_text(value)
        return attrs


def blocked_response(text: str | None, *, context: str = "") -> Response | None:
    """Return a 400 Response when text is disallowed, else None."""
    try:
        check_text(text, context=context)
    except ContentPolicyViolation:
        return Response({"detail": POLICY_MESSAGE}, status=HTTP_400_BAD_REQUEST)
    return None
