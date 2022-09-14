import argparse
import asyncio
import sys

import httpx
import listparser
from asgiref.sync import sync_to_async
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from rich.progress import Progress

import feeds.crawler as crawler
from feeds.models import Category, Feed, Subscription

user = User.objects.first()


def ingest(resp, parsed, favicon, category_name):
    try:
        feed = crawler.ingest_feed(resp, parsed, favicon)
        if category_name:
            category, _ = Category.objects.get_or_create(name=category_name, user=user)
        else:
            category = None
        Subscription.objects.create(feed=feed, user=user, category=category)
    except Exception:
        breakpoint()


sync_ingest = sync_to_async(ingest)


async def import_feed(client, feed):
    print("Fetching:", feed["url"])
    resp, parsed_feed, favicon = await crawler.Crawler(client, feed["url"]).crawl()
    print("Got:", resp.url, resp.status_code)
    await sync_ingest(resp, parsed_feed, favicon, feed["categories"][0][0])


async def main(infile, workers):

    parsed = listparser.parse(infile.read())

    subscribed = set()
    async for url in Feed.objects.values_list("url", flat=True):
        subscribed.add(url)

    queue = asyncio.Queue()

    for feed in parsed["feeds"]:
        if feed["url"] not in subscribed:
            queue.put_nowait(feed)

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:

        with Progress() as progress:

            import_task = progress.add_task("Importing...", total=queue.qsize())

            async def worker():
                while True:
                    # Get a "work item" out of the queue.
                    feed = await queue.get()

                    # Sleep for the "sleep_for" seconds.
                    await import_feed(client, feed)

                    progress.advance(import_task)

                    # Notify the queue that the "work item" has been processed.
                    queue.task_done()

            # Create three worker tasks to process the queue concurrently.
            tasks = []
            for i in range(workers):
                task = asyncio.create_task(worker())
                tasks.append(task)

            # Wait until the queue is fully processed.
            await queue.join()

            # Cancel our worker tasks.
            for task in tasks:
                task.cancel()

            # Wait until all worker tasks are cancelled.
            await asyncio.gather(*tasks, return_exceptions=True)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "infile", nargs="?", type=argparse.FileType("r"), default=sys.stdin
        )
        parser.add_argument("--workers", nargs="?", type=int, default=100)

    def handle(self, *args, **options):
        asyncio.run(main(options["infile"], options["workers"]))
