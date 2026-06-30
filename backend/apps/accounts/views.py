import secrets
from datetime import datetime, timezone

from django.conf import settings
from django.contrib.auth import logout as django_logout
from django.shortcuts import redirect
from rest_framework import mixins, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .cognito import build_authorize_url, build_logout_url, decode_id_token, exchange_code
from .models import UserAPIKey
from .serializers import UserAPIKeySerializer, UserProfileSerializer
from .services import CognitoService


def _public_origin(request) -> str:
    """Proxy-aware public origin for post-auth redirects."""
    forwarded_host = request.META.get("HTTP_X_FORWARDED_HOST")
    if forwarded_host:
        # Reverse proxies may send comma-separated lists; first value is the client-facing one.
        host = forwarded_host.split(",")[0].strip()
        proto = (request.META.get("HTTP_X_FORWARDED_PROTO") or "https").split(",")[0].strip()
        return f"{proto}://{host}"
    configured = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    if configured:
        return configured
    return f"{request.scheme}://{request.get_host()}"


@api_view(["GET"])
def login(request):
    state = secrets.token_urlsafe(32)
    request.session["cognito_state"] = state
    request.session.save()
    return redirect(build_authorize_url(settings.COGNITO, state))


@api_view(["GET"])
def callback(request):
    code = request.GET.get("code", "")
    state = request.GET.get("state", "")
    expected_state = request.session.pop("cognito_state", None)

    if not expected_state or state != expected_state:
        return Response({"error": "Invalid state parameter"}, status=400)

    if not code:
        return Response({"error": "Missing authorization code"}, status=400)

    tokens = exchange_code(settings.COGNITO, code)
    if tokens is None:
        return Response({"error": "Token exchange failed"}, status=401)

    id_token = tokens.get("id_token", "")
    try:
        claims = decode_id_token(id_token)
    except Exception:
        return Response({"error": "Invalid ID token"}, status=401)

    sub = claims.get("sub")
    if not sub:
        return Response({"error": "ID token missing subject"}, status=401)

    CognitoService.get_or_create_profile(claims)

    # Rotate the session key on login to prevent session fixation.
    request.session.cycle_key()

    exp = claims.get("exp")
    if exp:
        expiry = datetime.fromtimestamp(exp, tz=timezone.utc)
        request.session.set_expiry(expiry)

    request.session["id_token"] = id_token
    request.session["access_token"] = tokens.get("access_token", "")
    request.session["refresh_token"] = tokens.get("refresh_token", "")
    request.session["cognito_sub"] = sub

    return redirect(f"{_public_origin(request)}/home")


@api_view(["GET", "POST"])
def logout(request):
    django_logout(request)
    return redirect(build_logout_url(settings.COGNITO))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserProfileSerializer(request.user).data)


class UserAPIKeyViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = UserAPIKeySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserAPIKey.objects.filter(
            owner=self.request.user,
        ).select_related("provider")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
