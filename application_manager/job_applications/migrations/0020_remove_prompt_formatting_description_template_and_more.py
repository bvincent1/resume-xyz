# Generated by Django 5.1.7 on 2025-03-24 16:53

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("job_applications", "0019_prompt_resume_replace_path_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="prompt",
            name="formatting_description_template",
        ),
        migrations.RemoveField(
            model_name="prompt",
            name="formatting_response_template",
        ),
        migrations.RemoveField(
            model_name="prompt",
            name="resume_replace_path",
        ),
    ]
