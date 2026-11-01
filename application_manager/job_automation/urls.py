from django.urls import path

from .views import JobURLView

urlpatterns = [
    path("job-urls/", JobURLView.as_view(), name="job-url-create"),
]
