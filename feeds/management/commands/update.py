import asyncio
import io
from typing import Optional

import dateutil.parser
import httpx
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.http import http_date
from rich.progress import track

import feeds.parser as parser
from feeds.models import Entry, Feed

USER_AGENT = "feedreader/1 +https://github.com/Jackevansevo/feedreader/"


async def update_feed(client, url, etag=None, last_modified=None):
    headers = {"User-Agent": USER_AGENT}
    if etag is not None:
        headers["If-None-Match"] = etag
    if last_modified is not None:
        headers["If-Modified-Since"] = http_date(int(last_modified.strftime("%s")))
    return await client.get(url, headers=headers)


async def main(filter: Optional[str]):

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:

        feed_query = Feed.objects.values("url", "etag", "last_modified")
        if filter is not None:
            feed_query = feed_query.filter(url__icontains=filter)

        tasks = [update_feed(client, **kwargs) async for kwargs in feed_query]
        total_tasks = len(tasks)

        for task in track(
            asyncio.as_completed(tasks), total=total_tasks, description="Updating..."
        ):
            result = await task

            if isinstance(result, Exception):
                continue

            lookup_url = result.url
            if result.history:
                lookup_url = result.history[0].url

            try:
                feed = await Feed.objects.aget(url=lookup_url)
            except Feed.DoesNotExist:
                breakpoint()

            update_fields = ["last_checked"]
            feed.last_checked = timezone.now()

            # If we were redirected, update to the new URL
            if result.history:
                print(f"{feed.url} redirected -> {result.url}")
                feed.url = str(result.url)
                update_fields.append("url")

            if result.status_code == 200:

                parsed = parser.parse(io.BytesIO(result.content))
                existing_entries = set()

                async for link in Entry.objects.filter(
                    feed__url=result.url
                ).values_list("link", flat=True):
                    existing_entries.add(link)

                for entry in parsed["entries"]:
                    link = entry.get("link")
                    if link is not None and link not in existing_entries:
                        entry = parser.parse_feed_entry(entry, feed)
                        await sync_to_async(entry.save)()

                etag = result.headers.get("etag")
                if etag is not None:
                    update_fields.append("etag")
                    feed.etag = etag

                last_modified = result.headers.get("last-modified")
                if last_modified is not None:
                    update_fields.append("last_modified")
                    feed.last_modified = dateutil.parser.parse(last_modified)

            await sync_to_async(feed.save)(update_fields=update_fields)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--filter",
            nargs="?",
            type=str,
        )

    def handle(self, *args, **options):
        asyncio.run(main(options["filter"]))
