# Generated by Django 4.1 on 2022-08-19 18:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("feeds", "0010_alter_feed_favicon"),
    ]

    operations = [
        migrations.AlterField(
            model_name="feed",
            name="favicon",
            field=models.ImageField(blank=True, null=True, upload_to=""),
        ),
    ]