import django.db.models.deletion
from django.db import migrations, models


def assign_default_provider(apps, schema_editor):
    """Give every existing application a provider before the FK becomes required."""
    Application = apps.get_model("job_applications", "Application")
    PromptProvider = apps.get_model("job_applications", "PromptProvider")

    applications = Application.objects.filter(provider__isnull=True)
    if not applications.exists():
        return

    provider = PromptProvider.objects.filter(name="gpt-4.1").first()
    if provider is None:
        provider = PromptProvider.objects.create(
            name="gpt-4.1",
            url="",
            headers={},
        )
    applications.update(provider=provider)


def delete_prompts(apps, schema_editor):
    """Remove the old per-section prompt rows before collapsing to one-to-one."""
    Prompt = apps.get_model("job_applications", "Prompt")
    Prompt.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("job_applications", "0034_prompt_error_prompt_provider_prompt_template_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="provider",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="applications",
                to="job_applications.promptprovider",
                help_text="Model provider used for the single tuning call.",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="tuning",
            field=models.JSONField(
                blank=True,
                null=True,
                help_text="Full JSON Resume document validated against json-resume-api/schema.json.",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="company_research",
            field=models.TextField(
                blank=True,
                null=True,
                help_text="Cached TinyFish company brief used for tuning.",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="company_researched_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(assign_default_provider, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="application",
            name="provider",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="applications",
                to="job_applications.promptprovider",
                help_text="Model provider used for the single tuning call.",
            ),
        ),
        migrations.RunPython(delete_prompts, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="prompt",
            name="provider",
        ),
        migrations.RemoveField(
            model_name="prompt",
            name="parent",
        ),
        migrations.RemoveField(
            model_name="prompt",
            name="name",
        ),
        migrations.AlterField(
            model_name="prompt",
            name="application",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="prompt",
                to="job_applications.application",
            ),
        ),
        migrations.AlterField(
            model_name="promptprovider",
            name="name",
            field=models.CharField(
                help_text="Model id sent to the API, e.g. 'openai/gpt-4.1'. Selected per application through Application.provider.",
                unique=True,
            ),
        ),
    ]
