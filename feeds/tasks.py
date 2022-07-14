from urllib.parse import urlparse

import feedparser
import httpx
from celery import group, shared_task
from dateutil import parser
from django.db import transaction
from django.db.models import Count
from django.utils.http import http_date

from feeds.models import Category, Feed, Subscription

# TODO work out why https://www.jntrnr.com/atom.xml fails in live

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
        feed, _ = _refresh_or_create_feed(url)
        Subscription.objects.get_or_create(
            feed=feed, user_id=user_id, category=category
        )
    return {"url": feed.get_absolute_url(), "link": feed.link}


def _refresh_or_create_feed(url):
    # TODO: Could we avoid multiple trips to the DB to get/update the feed

    feed, created = Feed.objects.get_or_create(url=url)

    headers = {"User-Agent": USER_AGENT}

    if feed.etag is not None:
        headers["If-None-Match"] = feed.etag
    if feed.last_modified is not None:
        headers["If-Modified-Since"] = http_date(feed.last_modified.timestamp())

    resp = httpx.get(feed.url, headers=headers, follow_redirects=True)

    parsed = feedparser.parse(resp)

    # TODO check if 'lasted_checked' auto_now field is updated on save with
    # updated_fields

    update_fields = []

    if created:
        feed.link = parsed.feed.link

        if parsed.feed.title != "":
            feed.title = parsed.feed.title
        else:
            feed.title = urlparse(parsed.feed.link).netloc.lstrip("www.")

        update_fields = ["title", "slug", "link"]

    if resp.status_code == 304:
        return feed, False

    # Temporary redirect
    if resp.history:
        feed.url = resp.url
        update_fields.append("url")

    # https://feedparser.readthedocs.io/en/latest/http-etag.html

    if resp.headers.get("etag"):
        feed.etag = resp.headers["etag"]
        update_fields.append("etag")
    if resp.headers.get("last-modified"):
        feed.last_modified = parser.parse(resp.headers["last-modified"])
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
