import uuid

from django.db import models


class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(blank=False, null=False)
    company_url = models.URLField(blank=True, null=True)


class Posting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    title = models.CharField(blank=False, null=False)
    description = models.TextField(blank=False, null=False)
    posting_url = models.URLField(blank=False, null=False)
