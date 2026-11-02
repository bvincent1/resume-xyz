from django.db import models, transaction


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

    def _url_changed(self) -> bool:
        """Return True when this save introduces a new posting URL."""
        if self._state.adding or self.pk is None:
            return True
        stored = JobURL.objects.filter(pk=self.pk).values_list("url", flat=True).first()
        return stored != self.url

    def save(self, dispatch: bool = True, **kwargs):
        scan = (
            dispatch
            and self._url_changed()
            and self.application_id is None
            and self.status_id is not None
            and self.status.name == "todo"
        )
        super().save(**kwargs)
        if scan:
            from .tasks import dispatch_scan

            transaction.on_commit(lambda: dispatch_scan(self.pk))
