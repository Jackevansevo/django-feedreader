from __future__ import annotations

import uuid
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.core.validators import MinLengthValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from unidecode import unidecode

# TODO Cleanup


class Category(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField()
    user: models.ForeignKey = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE
    )

    class Meta:
        unique_together = [["slug", "user"]]
        verbose_name_plural = "categories"

    def get_absolute_url(self):
        return reverse("feeds:category-detail", kwargs={"slug": self.slug})

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super(Category, self).save(*args, **kwargs)

    def __str__(self):
        return self.name


class Feed(models.Model):
    title = models.CharField(
        max_length=300, blank=False, validators=[MinLengthValidator(1)]
    )
    subtitle = models.TextField(blank=True, null=True)
    slug = models.SlugField(max_length=200)
    link = models.URLField()
    url = models.URLField(unique=True)
    etag = models.CharField(max_length=200, blank=True, null=True)
    last_modified = models.DateTimeField(null=True)
    last_checked = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def find_feed_from_url(cls, url):
        # TODO Cleanup this mess
        parsed = urlparse(url)

        if parsed.netloc.endswith("wordpress.com") or parsed.netloc.endswith(
            "bearblog.dev"
        ):
            if not parsed.path.endswith("/feed/"):
                return parsed._replace(path=f"{parsed.path}/feed/").geturl()
        elif parsed.netloc.endswith("substack.com"):
            if not parsed.path.endswith("/feed"):
                return parsed._replace(path=f"{parsed.path}/feed").geturl()
        elif parsed.netloc.endswith("tumblr.com"):
            if parsed.path != "/rss":
                return urljoin(url, "rss")
        elif parsed.netloc.endswith("medium.com"):
            if not parsed.path.startswith("/feed"):
                return parsed._replace(path=f"feed{parsed.path}").geturl()
        elif parsed.netloc.endswith("blogspot.com"):
            if parsed.path != "/feeds/posts/default":
                return urljoin(url, "feeds/posts/default")

        return url

    def get_absolute_url(self):
        return reverse("feeds:feed-detail", kwargs={"feed_slug": self.slug})

    def save(self, *args, **kwargs):
        self.slug = slugify(unidecode(self.title))
        super(Feed, self).save(*args, **kwargs)

    class Meta:
        ordering = ["title", "-last_modified"]

    def __str__(self):
        return self.title


class Subscription(models.Model):
    feed = models.ForeignKey(
        Feed, on_delete=models.CASCADE, related_name="subscriptions"
    )
    user: models.ForeignKey = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="subscriptions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def get_absolute_url(self):
        return reverse("feeds:feed-detail", kwargs={"feed_slug": self.feed.slug})

    class Meta:
        unique_together = [["feed", "user"]]


class Entry(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    title = models.CharField(
        max_length=300, blank=False, validators=[MinLengthValidator(1)]
    )
    link = models.URLField(max_length=300)
    feed = models.ForeignKey(Feed, on_delete=models.CASCADE, related_name="entries")
    published = models.DateTimeField(null=True)
    updated = models.DateTimeField(null=True)
    slug = models.SlugField(max_length=300)
    content = models.TextField(blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    guid = models.CharField(max_length=400, blank=True, null=True, unique=True)
    author = models.CharField(max_length=400, blank=True, null=True)
    thumbnail = models.URLField(blank=True, null=True, max_length=500)

    def get_absolute_url(self):
        return reverse(
            "feeds:entry-detail",
            kwargs={
                "entry_slug": self.slug,
                "uuid": self.uuid,
                "feed_slug": self.feed.slug,
            },
        )

    def __str__(self):
        return self.title

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["feed", "guid"], name="duplicate guid"),
            models.UniqueConstraint(fields=["feed", "link"], name="duplicate link"),
        ]
        verbose_name_plural = "entries"
        ordering = ["-published", "title"]
        indexes = [
            models.Index(fields=["guid"]),
        ]
