from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import LLMModelViewSet, ProjectViewSet, SceneViewSet

router = DefaultRouter()
router.register(r"projects", ProjectViewSet, basename="project")
router.register(r"models", LLMModelViewSet, basename="llmmodel")

urlpatterns = router.urls + [
    path(
        "projects/<uuid:project_pk>/scenes/",
        SceneViewSet.as_view({"get": "list"}),
        name="project-scenes-list",
    ),
    path(
        "projects/<uuid:project_pk>/scenes/<int:index>/",
        SceneViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="project-scenes-detail",
    ),
    path(
        "projects/<uuid:project_pk>/scenes/<int:index>/media-urls/",
        SceneViewSet.as_view({"get": "media_urls"}),
        name="project-scenes-media-urls",
    ),
    path(
        "projects/<uuid:project_pk>/scenes/<int:index>/regenerate/",
        SceneViewSet.as_view({"post": "regenerate"}),
        name="project-scenes-regenerate",
    ),
    path(
        "projects/<uuid:project_pk>/scenes/<int:index>/revoice/",
        SceneViewSet.as_view({"post": "revoice"}),
        name="project-scenes-revoice",
    ),
]
