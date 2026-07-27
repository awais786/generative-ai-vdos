from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register("keys", views.UserAPIKeyViewSet, basename="apikey")

urlpatterns = [
    path("login", views.login, name="login"),
    path("callback", views.callback, name="callback"),
    path("logout", views.logout, name="logout"),
    path("me", views.me, name="me"),
    path("dev-login", views.dev_login, name="dev_login"),
    path("", include(router.urls)),
]
