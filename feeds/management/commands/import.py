import argparse
import asyncio
import sys

import httpx
import listparser
from asgiref.sync import sync_to_async
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

import feeds.crawler as crawler
from feeds.models import Category, Feed, Subscription

user = User.objects.first()

limit = asyncio.Semaphore(200)


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
    async with limit:
        print("Fetching:", feed["url"])
        resp, parsed_feed, favicon = await crawler.Crawler(client, feed["url"]).crawl()
        print("Got:", resp.url, resp.status_code)
        await sync_ingest(resp, parsed_feed, favicon, feed["categories"][0][0])

        if limit.locked():
            print("Limit reached, sleeping temporarily")
            await asyncio.sleep(0.5)


async def main(infile):

    parsed = listparser.parse(infile.read())

    subscribed = set()
    async for url in Feed.objects.values_list("url", flat=True):
        subscribed.add(url)

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        await asyncio.gather(
            *[
                import_feed(client, feed)
                for feed in parsed["feeds"]
                if feed["url"] not in subscribed
            ],
        )


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "infile", nargs="?", type=argparse.FileType("r"), default=sys.stdin
        )

    def handle(self, *args, **options):
        asyncio.run(main(options["infile"]))
