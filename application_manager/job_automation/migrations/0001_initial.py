import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("job_applications", "0039_promptprovider_model"),
    ]

    operations = [
        # The tables already exist (they were created by job_applications/0024)
        # and are kept in place, so only the state changes here.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="URLStatus",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("name", models.CharField()),
                    ],
                    options={
                        "db_table": "job_applications_urlstatus",
                    },
                ),
                migrations.CreateModel(
                    name="JobURL",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("url", models.URLField(unique=True)),
                        (
                            "status",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT,
                                to="job_automation.urlstatus",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "job_applications_joburl",
                    },
                ),
            ],
        ),
    ]
