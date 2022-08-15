import httpx
from celery import chain, group, shared_task
from celery.exceptions import Ignore
from celery.utils.log import get_task_logger
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.http import http_date

from feeds.models import Category, Entry, Feed, Subscription

from .parser import parse_feed, parse_feed_entry

USER_AGENT = "feedreader/1 +https://github.com/Jackevansevo/feedreader/"

logger = get_task_logger(__name__)

# TODO Make the retry policy error specific

timeout = httpx.Timeout(10.0, connect=60.0)
limits = httpx.Limits(
    max_keepalive_connections=None, max_connections=None, keepalive_expiry=10
)
client = httpx.Client(timeout=timeout, limits=limits, follow_redirects=True)


@shared_task(
    autoretry_for=(httpx.TimeoutException,),
    retry_backoff=True,
    acks_late=True,
    task_reject_on_worker_lost=True,
)
def fetch_feed(url, last_modified=None, etag=None):
    headers = {"User-Agent": USER_AGENT}

    if etag is not None:
        headers["If-None-Match"] = etag
    if last_modified is not None:
        headers["If-Modified-Since"] = http_date(last_modified.timestamp())

    resp = client.get(url, headers=headers)

    return {
        "status": resp.status_code,
        "url": str(resp.url),
        "body": resp.read(),
        "headers": {
            "etag": resp.headers.get("etag"),
            "content-type": resp.headers.get("content-type"),
            "last-modified": resp.headers.get("last-modified"),
        },
    }


def create_subscription(url, category_name, user_id):
    return chain(
        fetch_feed.s(url),
        add_subscription.s(category_name, user_id),
    )


@shared_task(acks_late=True, task_reject_on_worker_lost=True)
def add_subscription(resp, category_name, user_id):

    parsed, entries = parse_feed(resp)

    with transaction.atomic():

        feed = Feed.objects.create(**parsed)
        logger.info(f"feed {feed.id} {feed}")

        # Impossible to use a set because entries aren't hashable
        unique_entries = dict()
        for entry in entries:
            # When adding a new feed for entries with the
            # same link, we only want to take the most
            # recent
            if entry.link not in unique_entries:
                unique_entries[entry.link] = entry

        parsed_entries = (
            parse_feed_entry(entry, feed) for entry in unique_entries.values()
        )

        Entry.objects.bulk_create(
            entry for entry in parsed_entries if entry is not None
        )

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

    feed = Feed.objects.prefetch_related("entries").get(id=feed_id)
    feed.last_checked = timezone.now()

    if resp["status"] == 304:
        logger.info(f"{url} Nothing to update")
        feed.save(update_fields=["last_checked"])
        return {"id": feed.id, "url": url, "updated": False}

    parsed, entries = parse_feed(resp)

    if entries:
        existing_entries = feed.entries.values("link", "guid").order_by("published")

        guids = {entry["guid"] for entry in existing_entries}
        links = {entry["link"] for entry in existing_entries}

        new_entries = []

        for entry in entries:
            if hasattr(entry, "guid") and not getattr(entry, "guidislink", True):
                if entry.guid not in guids:
                    new_entries.append(entry)
            else:
                if entry.link not in links:
                    new_entries.append(entry)

        logger.debug(f"new_entries: {new_entries}")

        updated = False
        parsed_entries = (parse_feed_entry(entry, feed) for entry in new_entries)
        for entry in parsed_entries:

            if entry is None:
                continue

            try:
                feed.entries.add(entry, bulk=False)
            except IntegrityError as err:
                logger.warn(f"IntegrityError: {err}")
            else:
                updated = True

        for attr, value in parsed.items():
            setattr(feed, attr, value)

        feed.save()

        return {"id": feed.id, "url": feed.url, "updated": updated}

    else:
        return {"id": feed.id, "url": feed.url, "updated": False}


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
