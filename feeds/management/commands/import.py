import argparse
import asyncio
import sys

import httpx
import listparser
from django.core.management.base import BaseCommand

from feeds.models import Subscription, Category, Feed
from django.contrib.auth.models import User
import feeds.crawler as crawler
from asgiref.sync import sync_to_async

USER_AGENT = "feedreader/1 +https://github.com/Jackevansevo/feedreader/"

user = User.objects.first()


def ingest(resp, parsed, favicon, category):
    try:
        feed = crawler.ingest_feed(resp, parsed, favicon)
        category, _ = Category.objects.get_or_create(name=category, user=user)
        Subscription.objects.create(feed=feed, user=user, category=category)
    except Exception:
        breakpoint()


sync_ingest = sync_to_async(ingest)


async def crawl_url(client, url):
    return await crawler.Crawler(client, url).crawl()


async def main(infile):

    parsed = listparser.parse(infile.read())

    timeout = httpx.Timeout(10.0)
    limits = httpx.Limits(
        max_keepalive_connections=None, max_connections=None, keepalive_expiry=10
    )

    subscribed = set()
    async for url in Feed.objects.values_list("url", flat=True):
        subscribed.add(url)

    async with httpx.AsyncClient(
        timeout=timeout, limits=limits, follow_redirects=True
    ) as client:
        for feed in parsed["feeds"]:
            print(feed["url"])
            if feed["url"] not in subscribed:
                resp = await crawl_url(client, feed["url"])
                await sync_ingest(*resp, feed["categories"][0][0])


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "infile", nargs="?", type=argparse.FileType("r"), default=sys.stdin
        )

    def handle(self, *args, **options):
        asyncio.run(main(options["infile"]))
