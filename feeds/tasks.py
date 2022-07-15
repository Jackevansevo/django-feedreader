from urllib.parse import urlparse

import feedparser
import httpx
from celery import group, shared_task
from dateutil import parser
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.http import http_date

from feeds.models import Category, Feed, Subscription

# TODO: Optimize with eventlet:
# https://github.com/celery/celery/tree/master/examples/eventlet

USER_AGENT = "feedreader/1 +https://github.com/Jackevansevo/feedreader/"


@shared_task
def add_subscription(url, category_name, user_id):
    with transaction.atomic():
        if category_name is not None:
            category, _ = Category.objects.get_or_create(
                name=category_name, user_id=user_id
            )
        else:
            category = None
        feed, _, _ = _refresh_or_create_feed(url)
        Subscription.objects.get_or_create(
            feed=feed, user_id=user_id, category=category
        )
    return {"url": feed.get_absolute_url(), "link": feed.link}


def _refresh_or_create_feed(url, last_modified=None, etag=None):
    # TODO: Could we avoid multiple trips to the DB to get/update the feed

    headers = {"User-Agent": USER_AGENT}

    if etag is not None:
        headers["If-None-Match"] = etag
    if last_modified is not None:
        headers["If-Modified-Since"] = http_date(last_modified.timestamp())

    resp = httpx.get(url, headers=headers, follow_redirects=True)

    if resp.status_code == 304:
        return url, False, False

    parsed = feedparser.parse(resp)

    # TODO check if 'lasted_checked' auto_now field is updated on save with
    # updated_fields

    update_fields = {"last_checked": timezone.now()}

    update_fields["link"] = parsed.feed.link

    if parsed.feed.title != "":
        update_fields["title"] = parsed.feed.title
    else:
        update_fields["title"] = urlparse(parsed.feed.link).netloc.lstrip("www.")

    # Temporary redirect
    if resp.history:
        update_fields["url"] = resp.url

    # https://feedparser.readthedocs.io/en/latest/http-etag.html

    if resp.headers.get("etag"):
        update_fields["etag"] = resp.headers["etag"]
    if resp.headers.get("last-modified"):
        update_fields["last_modified"] = parser.parse(resp.headers["last-modified"])

    feed, created = Feed.objects.update_or_create(url=url, defaults=update_fields)

    if parsed.entries:
        updated = feed.add_new_entries(parsed.entries)
        return feed, created, updated
    else:
        return feed, created, False


@shared_task
def refresh_feeds():
    feeds = (
        Feed.objects.annotate(subscribers=Count("subscriptions"))
        .filter(subscribers__gt=0)
        .values_list("url", "last_modified", "etag")
    )
    return group(
        refresh_or_create_feed.s(url, last_modified, etag)
        for (url, last_modified, etag) in feeds
    ).apply_async()


@shared_task
def refresh_or_create_feed(url, last_modified=None, etag=None):
    feed, created, updated = _refresh_or_create_feed(url)
    return {
        "feed": {
            "url": feed.url,
            "last_modified": feed.last_modified,
            "etag": feed.etag,
            "updated": updated,
            "created": created,
        }
    }


@shared_task
def delete_unsubscribed_feeds():
    Feed.objects.prefetch_related("subscriptions").annotate(
        subscribers=Count("subscriptions")
    ).filter(subscribers=0).delete()
