from django.db import migrations, models
from django.db.models import F


def backfill_model(apps, schema_editor):
    """Existing providers stored their model id in `name`."""
    PromptProvider = apps.get_model("job_applications", "PromptProvider")
    PromptProvider.objects.filter(model="").update(model=F("name"))


class Migration(migrations.Migration):

    dependencies = [
        ("job_applications", "0038_remove_promptprovider_headers"),
    ]

    operations = [
        migrations.AddField(
            model_name="promptprovider",
            name="model",
            field=models.CharField(
                default="",
                help_text="Model id sent to the API, e.g. 'openai/gpt-4.1'.",
                max_length=255,
            ),
        ),
        migrations.RunPython(backfill_model, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="promptprovider",
            name="name",
            field=models.CharField(
                help_text="Provider name or label, e.g. 'OpenRouter'. Selected per application through Application.provider.",
                unique=True,
            ),
        ),
    ]
