from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from unfold.admin import ModelAdmin
from unfold.decorators import action

from .models import JobURL, URLStatus
from .tasks import scan_job_url_task


class URLStatusAdmin(ModelAdmin):
    pass


class JobURLAdmin(ModelAdmin):
    list_display = ("__str__", "url", "status", "application")
    list_filter = ("status",)
    readonly_fields = ("application", "error")
    actions = ["scan_selected"]
    actions_detail = ["scan_now"]

    @action(description="Scan selected URLs")
    def scan_selected(self, request, queryset):
        for job_url in queryset:
            scan_job_url_task.delay(job_url.pk)
        self.message_user(request, "Scans queued.")

    @action(description="Scan now", url_path="scan-now")
    def scan_now(self, request, object_id: int):
        scan_job_url_task.delay(object_id)
        self.message_user(request, "Scan queued.")
        return redirect(reverse_lazy("admin:job_automation_joburl_changelist"))


admin.site.register(URLStatus, URLStatusAdmin)
admin.site.register(JobURL, JobURLAdmin)
