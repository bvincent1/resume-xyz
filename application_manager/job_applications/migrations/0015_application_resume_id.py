# Generated by Django 5.1.7 on 2025-03-21 19:38

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("job_applications", "0014_alter_application_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="resume_id",
            field=models.CharField(blank=True, null=True),
        ),
    ]
