# Generated by Django 4.0.6 on 2022-07-15 11:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feeds", "0005_alter_entry_unique_together"),
    ]

    operations = [
        migrations.AlterField(
            model_name="feed",
            name="slug",
            field=models.SlugField(max_length=200, unique=True),
        ),
    ]
