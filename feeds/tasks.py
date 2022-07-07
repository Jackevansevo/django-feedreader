from datetime import datetime
from time import mktime

import feedparser
from celery import group, shared_task
from django.db import transaction
from django.db.models import Count

from feeds.models import Feed, Subscription


def _fetch_feed(url):
    try:
        return Feed.objects.get(url=url)
    except Feed.DoesNotExist:
        parsed = feedparser.parse(url)
        feed = Feed.from_parsed_feed(parsed)
        feed.save()
        return feed


@shared_task
def add_subscription(url, category_id, user_id):
    # FIXME Do I need this transaction here?
    with transaction.atomic():
        feed = _fetch_feed(url)
        subscription, created = Subscription.objects.get_or_create(
            feed=feed, user_id=user_id, category_id=category_id
        )
    return {"url": feed.get_absolute_url(), "link": feed.link}


@shared_task
def fetch_feed(url):
    feed = fetch_feed(url)

    return {
        "feed": {
            "id": feed.id,
            "url": feed.url,
            "last_modified": feed.last_modified,
            "etag": feed.etag,
        }
    }


def _refresh_feed(feed_id, url, last_modified, etag):
    parsed = feedparser.parse(url, modified=last_modified, etag=etag)

    try:
        feed = Feed.objects.get(id=feed_id)
    except Feed.DoesNotExist:
        return None

    update_fields = []

    # Temporary redirect
    if parsed.status == 301:
        feed.url = parsed.href
        update_fields.append("url")

    if hasattr(parsed, "etag"):
        feed.etag = parsed.etag
        update_fields.append("etag")
    if hasattr(parsed, "modified_parsed"):
        # TODO the latest version of feedparser has broken this fuck
        feed.last_modified = datetime.fromtimestamp(mktime(parsed.modified_parsed))
        update_fields.append("last_modified")

    feed.update_entries(parsed.entries)

    updated = False

    if update_fields:
        feed.save(update_fields=update_fields)

    return {
        "feed": {
            "id": feed_id,
            "url": url,
            "last_modified": feed.last_modified,
            "etag": feed.etag,
            "updated": updated,
        }
    }


@shared_task
def refresh_feeds():
    feeds = Feed.objects.values_list("id", "url", "last_modified", "etag")
    g = group(
        refresh_feed.s(id, url, last_modified, etag)
        for (id, url, last_modified, etag) in feeds
    )
    res = g()
    return res


@shared_task
def refresh_feed(feed_id, url, last_modified, etag):
    return _refresh_feed(feed_id, url, last_modified, etag)


@shared_task
def delete_unsubscribed_feeds():
    Feed.objects.prefetch_related("subscriptions").annotate(
        subscribers=Count("subscriptions")
    ).filter(subscribers=0).delete()
