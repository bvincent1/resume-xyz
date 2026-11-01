from django.db import models


class URLStatus(models.Model):
    name = models.CharField(blank=False, null=False)

    class Meta:
        # The model moved here from job_applications; keep the existing table.
        db_table = "job_applications_urlstatus"

    def __str__(self):
        return self.name


class JobURL(models.Model):
    url = models.URLField(unique=True, blank=False, null=False)
    status = models.ForeignKey(
        URLStatus,
        null=False,
        blank=False,
        on_delete=models.PROTECT,
    )
    application = models.OneToOneField(
        "job_applications.Application",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_url_record",
    )
    error = models.TextField(null=True, blank=True)

    class Meta:
        # The model moved here from job_applications; keep the existing table.
        db_table = "job_applications_joburl"

    def __str__(self):
        return f"{self.status}-{self.url}"
