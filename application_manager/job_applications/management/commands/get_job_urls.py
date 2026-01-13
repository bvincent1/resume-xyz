from django.apps import apps
from django.core.management.base import BaseCommand
from pprint import pprint
from subprocess import run, PIPE
from json import loads
from job_applications.models import JobURL, URLStatus


class Command(BaseCommand):
    help = "Get job posting urls from search page"

    def handle(self, *args, **kwargs):

        url = "https://www.linkedin.com/jobs/search/?keywords=Full%20Stack%20Engineer&location=Canada&geoId=101174742&f_TPR=r86400&f_WT=2&position=1&pageNum=0"
        result = run(
            ["node", "../scraper/src/getSearchResults.mjs", url],
            cwd=apps.get_app_config("job_applications").path,
            stderr=PIPE,
            stdout=PIPE,
            text=True,
        )
        if result.returncode == 0:
            result_urls = loads(result.stdout)
            for u in result_urls:
                try:
                    JobURL(url=u, status=URLStatus.objects.get(name="todo")).save()
                except:
                    print(f"something went wrong trying to parse: {u}")

            self.stdout.write(
                self.style.SUCCESS(f"Successfully scrapped urls, {len(result_urls)}")
            )
