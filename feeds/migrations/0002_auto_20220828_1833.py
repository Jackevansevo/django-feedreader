import os

from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib.sites.models import Site
from django.db import migrations, transaction


def create_site(apps, schema_editor):
    with transaction.atomic():
        if settings.DEBUG:
            site, _ = Site.objects.get_or_create(
                name="localhost", domain="localhost:8000"
            )
            social_app = SocialApp.objects.create(
                provider="google",
                name="google",
                client_id=os.environ.get("GOOGLE_CLIENT_ID"),
                secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
            )
            social_app.sites.set([site])


class Migration(migrations.Migration):

    dependencies = [
        ("feeds", "0001_initial"),
        ("sites", "0002_alter_domain_unique"),
        ("socialaccount", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_site)]
