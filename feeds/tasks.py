from urllib.parse import urlparse

import feedparser
from celery import group, shared_task, chain
from dateutil import parser
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.http import http_date
from eventlet.green.urllib.request import Request, urlopen
from feeds.models import Category, Feed, Subscription, Entry

USER_AGENT = "feedreader/1 +https://github.com/Jackevansevo/feedreader/"


# TODO Make the retry policy error specific


@shared_task(autoretry_for=(Exception,), retry_backoff=True)
def fetch_feed(url, last_modified=None, etag=None):
    headers = {"User-Agent": USER_AGENT}

    if etag is not None:
        headers["If-None-Match"] = etag
    if last_modified is not None:
        headers["If-Modified-Since"] = http_date(last_modified.timestamp())

    request = Request(url, headers=headers)
    resp = urlopen(request, timeout=5)

    return {
        "status": resp.status,
        "url": resp.url,
        "body": resp.read(),
        "headers": {
            "etag": resp.headers.get("etag"),
            "last-modified": resp.headers.get("last-modified"),
        },
    }


@shared_task
def parse_response(resp):

    # TODO would it be better to split this up into a parser task + additional
    # DB worker task

    if resp["status"] == 304:
        # Nothing to update
        return

    parsed = feedparser.parse(resp["body"])

    update_fields = {"last_checked": timezone.now()}

    if parsed.feed.link == "":
        parsed.feed.link = resp["url"]

    update_fields["link"] = parsed.feed.link

    if parsed.feed.title != "":
        update_fields["title"] = parsed.feed.title
    else:
        update_fields["title"] = urlparse(parsed.feed.link).netloc.lstrip("www.")

    # https://feedparser.readthedocs.io/en/latest/http-etag.html

    headers = resp["headers"]

    if headers.get("etag"):
        update_fields["etag"] = headers["etag"]
    if headers.get("last-modified"):
        update_fields["last_modified"] = parser.parse(headers["last-modified"])

    feed, created = Feed.objects.update_or_create(
        url=resp["url"], defaults=update_fields
    )

    if parsed.entries:
        parsed_entries = (
            Entry.from_feed_entry(feed, dict(entry)) for entry in parsed.entries
        )
        updated = feed.add_new_entries(parsed_entries)
        return feed.url, created, bool(updated)
    else:
        return feed.url, created, False


def create_subscription(url, category_name, user_id):
    # TODO there is a subtle bug here if the feed URL changes, so we'd be
    # better off saving the feed ID from step 2 (parse_response) and then handling
    return chain(
        fetch_feed.s(url),
        parse_response.s(),
        add_subscription.si(url, category_name, user_id),
    )


@shared_task
def add_subscription(url, category_name, user_id):
    with transaction.atomic():
        if category_name is not None:
            category, _ = Category.objects.get_or_create(
                name=category_name, user_id=user_id
            )
        else:
            category = None
        feed = Feed.objects.get(url=url)
        Subscription.objects.get_or_create(
            feed=feed, user_id=user_id, category=category
        )
    return {"url": feed.get_absolute_url(), "link": feed.link}


@shared_task
def refresh_feeds():
    feeds = (
        Feed.objects.annotate(subscribers=Count("subscriptions"))
        .filter(subscribers__gt=0)
        .values_list("url", "last_modified", "etag")
    )
    return group(
        chain(fetch_feed.s(url), parse_response.s())
        for (url, last_modified, etag) in feeds
    ).apply_async()


@shared_task
def delete_unsubscribed_feeds():
    Feed.objects.prefetch_related("subscriptions").annotate(
        subscribers=Count("subscriptions")
    ).filter(subscribers=0).delete()
