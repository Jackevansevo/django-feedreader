from urllib.parse import urlparse

import httpx
import feedparser
from celery import chain, group, shared_task
from dateutil import parser
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.http import http_date
from celery.utils.log import get_task_logger

from feeds.models import Category, Entry, Feed, Subscription

USER_AGENT = "feedreader/1 +https://github.com/Jackevansevo/feedreader/"

logger = get_task_logger(__name__)

# TODO Make the retry policy error specific


@shared_task(autoretry_for=(httpx.RequestError,), retry_backoff=True)
def fetch_feed(url, last_modified=None, etag=None):
    headers = {"User-Agent": USER_AGENT}

    if etag is not None:
        headers["If-None-Match"] = etag
    if last_modified is not None:
        headers["If-Modified-Since"] = http_date(last_modified.timestamp())

    response = httpx.get(url, headers=headers, follow_redirects=True)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        print(
            f"Error response {exc.response.status_code} while requesting {exc.request.url!r}."
        )

    return {
        "status": response.status_code,
        "url": str(response.url),
        "body": response.read(),
        "headers": {
            "etag": response.headers.get("etag"),
            "last-modified": response.headers.get("last-modified"),
        },
    }


def parse_feed(resp):

    # TODO we probably want to move some of this logic into a separate parser
    # file and consolidate with Feed.from_feed_entry

    # TODO would it be possible just to build an in memory version of Feed / Entry and return it from this function
    # Then any data integrity issues would be solved when calling .save() ?

    # We also want updates to be efficient as well???

    if resp["status"] == 304:
        # Nothing to update
        return None, None

    parsed = feedparser.parse(resp["body"])

    feed = {"last_checked": timezone.now(), "url": resp["url"]}

    if parsed.feed.link == "":
        parsed.feed.link = resp["url"]

    feed["link"] = parsed.feed.link

    if parsed.feed.title != "":
        feed["title"] = parsed.feed.title
    else:
        feed["title"] = urlparse(parsed.feed.link).netloc.lstrip("www.")

    # https://feedparser.readthedocs.io/en/latest/http-etag.html

    headers = resp["headers"]

    if headers.get("etag"):
        feed["etag"] = headers["etag"]
    if headers.get("last-modified"):
        feed["last_modified"] = parser.parse(headers["last-modified"])

    return feed, parsed.entries


def create_subscription(url, category_name, user_id):
    return chain(
        fetch_feed.s(url),
        add_subscription.s(category_name, user_id),
    )


@shared_task
def add_subscription(resp, category_name, user_id):

    parsed, entries = parse_feed(resp)

    with transaction.atomic():

        feed = Feed.objects.create(**parsed)

        if entries:
            parsed_entries = (
                Entry.from_feed_entry(feed, dict(entry)) for entry in entries
            )
            feed.add_new_entries(parsed_entries, creating=True)

        if category_name is not None:
            category, _ = Category.objects.get_or_create(
                name=category_name, user_id=user_id
            )
        else:
            category = None
        Subscription.objects.get_or_create(
            feed=feed, user_id=user_id, category=category
        )
    return {"url": feed.get_absolute_url(), "link": feed.link}


@shared_task
def update_feed(resp, feed_id, url):
    parsed, entries = parse_feed(resp)
    if parsed is None:
        logger.info(f"{url} Nothing to update")
        Feed.objects.update_or_create(id=feed_id, last_checked=timezone.now())
        return
    feed, created = Feed.objects.update_or_create(id=feed_id, defaults=parsed)
    if entries:
        # TODO when upserting, we probaby don't need to bulk create? Can
        # probably just loop over the items and call add because there's only
        # likely to be one or two items
        parsed_entries = (Entry.from_feed_entry(feed, dict(entry)) for entry in entries)
        updated = feed.add_new_entries(parsed_entries)
    else:
        updated = False
    return {"url": feed.url, "updated": updated}


@shared_task
def refresh_feeds():
    feeds = (
        Feed.objects.annotate(subscribers=Count("subscriptions"))
        .filter(subscribers__gt=0)
        .values("id", "url", "last_modified", "etag")
    )
    return group(
        chain(
            fetch_feed.s(f["url"], f["last_modified"], f["etag"]),
            update_feed.s(f["id"], f["url"]),
        )
        for f in feeds
    ).apply_async()


@shared_task
def delete_unsubscribed_feeds():
    Feed.objects.prefetch_related("subscriptions").annotate(
        subscribers=Count("subscriptions")
    ).filter(subscribers=0).delete()
