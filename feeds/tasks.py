import feedparser
from celery import group, shared_task
from dateutil import parser
from django.db import transaction
from django.db.models import Count

from feeds.models import Category, Feed, Subscription


@shared_task
def ping():
    return "PONG"


@shared_task
def add_subscription(url, category_name, user_id):
    with transaction.atomic():
        if category_name is not None:
            category, _ = Category.objects.get_or_create(
                name=category_name, user_id=user_id
            )
        else:
            category = None
        feed, _ = _refresh_or_create_feed(url)
        Subscription.objects.get_or_create(
            feed=feed, user_id=user_id, category=category
        )
    return {"url": feed.get_absolute_url(), "link": feed.link}


def _refresh_or_create_feed(url):
    # TODO: Could we avoid multiple trips to the DB to get/update the feed

    feed, created = Feed.objects.get_or_create(url=url)
    parsed = feedparser.parse(feed.url, modified=feed.last_modified, etag=feed.etag)

    # TODO check if 'lasted_checked' auto_now field is updated on save with
    # updated_fields

    update_fields = []

    if created:
        feed.title = parsed.feed.get("title")
        feed.link = parsed.feed.get("link")
        update_fields = ["title", "slug", "link"]

    # Temporary redirect
    if parsed.status == 301:
        feed.url = parsed.href
        update_fields.append("url")

    # https://feedparser.readthedocs.io/en/latest/http-etag.html

    if hasattr(parsed, "etag"):
        feed.etag = parsed.etag
        update_fields.append("etag")
    if hasattr(parsed, "modified"):
        feed.last_modified = parser.parse(parsed.modified)
        update_fields.append("last_modified")

    if update_fields:
        feed.save(update_fields=update_fields)

    if parsed.entries:
        feed.add_new_entries(parsed.entries)

    return feed, bool(parsed.entries)


@shared_task
def refresh_feeds():
    feeds = (
        Feed.objects.annotate(subscribers=Count("subscriptions"))
        .filter(subscribers__gt=0)
        .values_list("url", flat=True)
    )
    g = group(refresh_or_create_feed.s(url) for url in feeds)
    res = g()
    return res


@shared_task
def refresh_or_create_feed(url):
    feed, updated = _refresh_or_create_feed(url)
    return {
        "feed": {
            "url": feed.url,
            "last_modified": feed.last_modified,
            "etag": feed.etag,
            "updated": updated,
        }
    }


@shared_task
def delete_unsubscribed_feeds():
    Feed.objects.prefetch_related("subscriptions").annotate(
        subscribers=Count("subscriptions")
    ).filter(subscribers=0).delete()
