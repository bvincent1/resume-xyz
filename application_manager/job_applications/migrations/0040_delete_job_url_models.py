from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("job_applications", "0039_promptprovider_model"),
        ("job_automation", "0002_joburl_scan_fields"),
    ]

    operations = [
        # Drop the models from job_applications state only; job_automation
        # reuses the same tables.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="JobURL"),
                migrations.DeleteModel(name="URLStatus"),
            ],
        ),
    ]
