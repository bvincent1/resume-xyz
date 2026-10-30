"""Django settings for the Playwright E2E stack."""

import dj_database_url

from .settings import *  # noqa: F401,F403


DATABASES = {
    "default": dj_database_url.config(
        env="E2E_POSTGRES_URL",
        default="postgres://postgres:postgres@127.0.0.1:55432/resume_e2e",
        conn_max_age=0,
    )
}

# The E2E stack has no worker or broker; admin actions run synchronously.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
