import shlex
import subprocess
import sys

from django.core.management.base import BaseCommand
from django.utils import autoreload


def restart_celery():
    cmd = 'pkill -f "celery worker"'
    if sys.platform == "win32":
        cmd = "taskkill /f /t /im celery.exe"

    subprocess.call(shlex.split(cmd))
    subprocess.call(
        shlex.split(
            "celery -q -A feedreader worker -E --without-heartbeat --without-mingle --without-gossip -l info -n scraper@%h --pool=eventlet --concurrency=500 -Q feeds"  # noqa
        )
    )


class Command(BaseCommand):
    def handle(self, *args, **options):
        print("Starting celery worker with autoreload...")
        autoreload.run_with_reloader(restart_celery)
