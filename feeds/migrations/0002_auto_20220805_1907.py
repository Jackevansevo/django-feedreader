# Generated by Django 4.1 on 2022-08-05 19:07

import os

from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib.sites.models import Site
from django.db import migrations


def create_site(apps, schema_editor):
    if settings.DEBUG:
        site = Site.objects.create(name="localhost", domain="localhost:8000")
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
