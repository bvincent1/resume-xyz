import os

from celery import Celery
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "application_manager.settings")
app = Celery("application_manager", broker="pyamqp://guest@localhost//")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps.
app.autodiscover_tasks(
    [
        "job_applications",
    ]
)
