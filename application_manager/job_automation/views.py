import secrets

from django.conf import settings
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import serializers
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import CreateAPIView

from .models import JobURL, URLStatus


class APIKeyAuthentication(BaseAuthentication):
    """Authenticate a request with the single API key from settings."""

    def authenticate(self, request):
        expected = settings.JOB_AUTOMATION_API_KEY
        supplied = request.headers.get("X-API-Key", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            raise AuthenticationFailed("Invalid API key.")
        return (None, None)

    def authenticate_header(self, request):
        # Returning a header makes DRF answer 401 instead of 403.
        return "X-API-Key"


class JobURLSerializer(serializers.ModelSerializer):
    status = serializers.SlugRelatedField(slug_field="name", read_only=True)

    class Meta:
        model = JobURL
        fields = ("id", "url", "status")


@extend_schema_view(
    post=extend_schema(
        summary="Create a job URL and queue a scan",
        responses={
            201: JobURLSerializer,
            401: OpenApiResponse(description="Invalid or missing API key."),
        },
    ),
)
class JobURLView(CreateAPIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = []
    serializer_class = JobURLSerializer

    def perform_create(self, serializer):
        status, _created = URLStatus.objects.get_or_create(name="todo")
        serializer.save(status=status)
