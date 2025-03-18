from django.contrib import admin

from .models import ApplicationStatus, Application, Prompt


admin.site.register(ApplicationStatus)
admin.site.register(Application)
admin.site.register(Prompt)
# Register your models here.
