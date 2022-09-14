import asyncio
import io
from typing import Optional

import dateutil.parser
import httpx
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.http import http_date
from urllib.parse import urljoin
from rich.progress import Progress

import feeds.parser as parser
from feeds.models import Entry, Feed

USER_AGENT = "feedreader/1 +https://github.com/Jackevansevo/feedreader/"


async def fetch_feed(client, url, etag=None, last_modified=None):
    headers = {"User-Agent": USER_AGENT}
    if etag is not None:
        headers["If-None-Match"] = etag
    if last_modified is not None:
        headers["If-Modified-Since"] = http_date(int(last_modified.strftime("%s")))
    return await client.get(url, headers=headers)


async def main(filter: Optional[str], workers):

    feed_query = Feed.objects.values("url", "etag", "last_modified")
    if filter is not None:
        feed_query = feed_query.filter(url__icontains=filter)

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        with Progress() as progress:

            queue = asyncio.Queue()

            results = asyncio.Queue()

            async for feed in feed_query:
                queue.put_nowait(feed)

            fetch_task = progress.add_task("Fetching...", total=queue.qsize())

            async def worker(queue, client):
                while True:
                    # Get a "work item" out of the queue.
                    feed = await queue.get()

                    # Sleep for the "sleep_for" seconds.
                    resp = await fetch_feed(client, **feed)

                    # Notify the queue that the "work item" has been processed.
                    queue.task_done()

                    results.put_nowait(resp)

                    progress.advance(fetch_task)

            # Create three worker tasks to process the queue concurrently.
            tasks = []
            for i in range(workers):
                task = asyncio.create_task(worker(queue, client))
                tasks.append(task)

            # Wait until the queue is fully processed.
            await queue.join()

            # Cancel our worker tasks.
            for task in tasks:
                task.cancel()

            # Wait until all worker tasks are cancelled.
            await asyncio.gather(*tasks, return_exceptions=True)

            async def process_results():
                while True:
                    result = await results.get()

                    print("Got response from:", result.url)

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
                            if (
                                link is not None
                                and urljoin(feed.link, link) not in existing_entries
                            ):
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

                    results.task_done()

            process_task = asyncio.create_task(process_results())

            await results.join()

            process_task.cancel()


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--filter",
            nargs="?",
            type=str,
        )
        parser.add_argument("--workers", nargs="?", type=int, default=100)

    def handle(self, *args, **options):
        asyncio.run(main(options["filter"], options["workers"]))
