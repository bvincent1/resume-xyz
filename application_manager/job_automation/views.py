import secrets

from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import JobURL, URLStatus
from .tasks import scan_job_url_task


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


class JobURLInputSerializer(serializers.Serializer):
    url = serializers.URLField()


class JobURLOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.URLField()
    status = serializers.CharField(source="status.name")


class JobURLConflictSerializer(serializers.Serializer):
    detail = serializers.CharField()
    id = serializers.IntegerField()


class JobURLView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = []

    @extend_schema(
        summary="Create a job URL and queue a scan",
        request=JobURLInputSerializer,
        responses={
            201: JobURLOutputSerializer,
            401: OpenApiResponse(description="Invalid or missing API key."),
            409: JobURLConflictSerializer,
        },
    )
    def post(self, request):
        data = JobURLInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        status, _created = URLStatus.objects.get_or_create(name="todo")
        job_url, created = JobURL.objects.get_or_create(
            url=data.validated_data["url"],
            defaults={"status": status},
        )
        if not created:
            return Response(
                JobURLConflictSerializer(
                    {"detail": "already exists", "id": job_url.pk}
                ).data,
                status=409,
            )

        transaction.on_commit(lambda: scan_job_url_task.delay(job_url.pk))

        return Response(
            JobURLOutputSerializer(job_url).data,
            status=201,
        )
