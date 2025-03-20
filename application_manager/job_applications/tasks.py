from celery import shared_task


@shared_task
def clear_tokens():
    from .models import Application, ApplicationStatus

    app = Application.objects.filter(
        status__exact=ApplicationStatus.objects.get(name__exact="todo").name
    ).first()

    # for p in app.list_prompts():
