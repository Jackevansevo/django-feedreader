# Generated by Django 4.1.1 on 2022-09-16 14:17

import datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feeds", "0002_auto_20220828_1833"),
    ]

    operations = [
        migrations.AlterField(
            model_name="feed",
            name="ttl",
            field=models.TimeField(default=datetime.time(1, 0)),
        ),
    ]
