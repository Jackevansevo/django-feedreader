import httpx
from django.db import IntegrityError, models, transaction
from dateutil import parser
from celery import chain, group, shared_task
from django.db.models import Count
from django.utils import timezone
from django.utils.http import http_date
from celery.utils.log import get_task_logger
from feeds.models import Category, Entry, Feed, Subscription

from .parser import parse_feed, parse_feed_entry

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
        logger.info(f"feed {feed.id} {feed}")

        if entries:
            parsed_entries = (parse_feed_entry(entry, feed) for entry in entries)
            with transaction.atomic():
                Entry.objects.bulk_create(parsed_entries)

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
        Feed.objects.update_or_create(
            id=feed_id, defaults={"last_checked": timezone.now()}
        )
        return {"url": url, "updated": False}

    feed = Feed.objects.prefetch_related("entries").get(id=feed_id)

    if entries:
        existing_entries = feed.entries.values("link", "guid").order_by("published")

        guids = {entry["guid"] for entry in existing_entries}
        links = {entry["link"] for entry in existing_entries}

        new_entries = []

        for entry in entries:
            if getattr(entry, "guidislink", False):
                if entry.link not in links:
                    new_entries.append(entry)
            else:
                if entry.guid not in guids:
                    new_entries.append(entry)

        logger.debug(f"new_entries: {new_entries}")

        updated = False
        parsed_entries = (parse_feed_entry(entry, feed) for entry in new_entries)
        for entry in parsed_entries:
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
