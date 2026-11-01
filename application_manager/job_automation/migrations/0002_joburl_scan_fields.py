import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("job_automation", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="joburl",
            name="application",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="job_url_record",
                to="job_applications.application",
            ),
        ),
        migrations.AddField(
            model_name="joburl",
            name="error",
            field=models.TextField(blank=True, null=True),
        ),
    ]
