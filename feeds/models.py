from __future__ import annotations

from urllib.parse import urljoin, urlparse

from dateutil import parser
from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from django.utils.text import slugify
from unidecode import unidecode

# TODO Cleanup


def generate_unique_slug(obj):
    # If slug is not unique
    attempt = 0
    slug = obj.slug
    while True:
        if attempt > 0:
            obj.slug = slug + str(attempt)
            print(f"trying slug: {obj.slug}")
        try:
            with transaction.atomic():
                obj.save()
                return
        except IntegrityError:
            print(f"slug integrity conflict: {obj.slug}")
            attempt = attempt + 1
            continue


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
    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
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

    def add_new_entries(self, entries):
        feed_entries = set(self.entries.values_list("link", "guid"))

        def not_exists(entry):
            return (entry.link, entry.guid) not in feed_entries

        # Attempt to figure out if entries have already been parsed
        new_entries = list(
            filter(
                not_exists,
                filter(
                    None,
                    [Entry.from_feed_entry(self, dict(entry)) for entry in entries],
                ),
            )
        )

        if new_entries:
            print(f"adding new entries for {self}", new_entries)

        try:
            # Attempt in a separate transaction
            with transaction.atomic():
                Entry.objects.bulk_create(new_entries)
        except IntegrityError:
            for entry in new_entries:
                generate_unique_slug(entry)

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
    title = models.CharField(max_length=300)
    link = models.URLField(unique=True, max_length=300)
    feed = models.ForeignKey(Feed, on_delete=models.CASCADE, related_name="entries")
    published = models.DateTimeField(null=True)
    updated = models.DateTimeField(null=True)
    slug = models.SlugField(max_length=300)
    content = models.TextField(blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    guid = models.CharField(max_length=400, blank=True, null=True, unique=True)
    author = models.CharField(max_length=400, blank=True, null=True)

    @classmethod
    def from_feed_entry(cls, feed, entry):

        content = entry.get("content")
        if content is not None:
            content = content[0]["value"]

        published = entry.get("published")
        if published is not None:
            try:
                published = parser.parse(published)
            except ValueError:
                return None

        updated = entry.get("updated")
        if updated is not None:
            try:
                updated = parser.parse(updated)
            except ValueError:
                return None

        if published is None and updated is not None:
            # Just for sorting
            published = updated

        title = entry["title"]

        return Entry(
            feed=feed,
            title=entry["title"],
            slug=slugify(unidecode(title)),
            link=entry["link"],
            published=published,
            updated=updated,
            content=content,
            author=entry.get("author"),
            summary=entry.get("summary"),
            guid=entry.get("guid"),
        )

    def get_absolute_url(self):
        return reverse(
            "feeds:entry-detail",
            kwargs={
                "entry_slug": self.slug,
                "feed_slug": self.feed.slug,
            },
        )

    def __str__(self):
        return self.title

    class Meta:
        unique_together = ("feed", "slug")
        verbose_name_plural = "entries"
        ordering = ["-published", "title"]
        indexes = [
            models.Index(fields=["guid"]),
        ]
