# Generated by Django 5.1.7 on 2025-03-21 17:30

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("job_applications", "0013_alter_prompt_options"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="application",
            options={"ordering": ["-id"]},
        ),
    ]
