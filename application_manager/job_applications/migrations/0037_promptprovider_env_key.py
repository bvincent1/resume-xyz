from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("job_applications", "0036_alter_application_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="promptprovider",
            name="env_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Environment variable holding the provider API key, e.g. 'OPENROUTER_API_KEY'.",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="promptprovider",
            name="headers",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Additional HTTP headers sent with every request. Auth comes from `env_key`, not from this mapping.",
            ),
        ),
    ]
