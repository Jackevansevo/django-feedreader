import argparse
import asyncio
import sys

import httpx
import listparser
from django.core.management.base import BaseCommand

from feeds.models import Subscription
from django.contrib.auth.models import User
import feeds.crawler as crawler
from asgiref.sync import sync_to_async

USER_AGENT = "feedreader/1 +https://github.com/Jackevansevo/feedreader/"

user = User.objects.first()


# def ingest(resp, parsed, favicon):
#     feed = crawler.ingest_feed(resp, parsed, favicon)
#     if feed:
#         Subscription.objects.create(feed=feed, user=user)
#     else:
#         print("failed to add", feed)
#
#
# sync_ingest = sync_to_async(ingest)


async def crawl_url(client, url):
    return await crawler.crawl(client, url)


async def main(infile):

    parsed = listparser.parse(infile.read())

    timeout = httpx.Timeout(10.0)
    limits = httpx.Limits(
        max_keepalive_connections=None, max_connections=None, keepalive_expiry=10
    )

    async with httpx.AsyncClient(
        timeout=timeout, limits=limits, follow_redirects=True
    ) as client:
        results = await asyncio.gather(
            *[
                asyncio.ensure_future(crawl_url(client, feed["url"]))
                for feed in parsed["feeds"]
            ],
        )
        for result in results:
            resp, parsed, favicon = result
            print(resp.url, parsed["link"], favicon)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "infile", nargs="?", type=argparse.FileType("r"), default=sys.stdin
        )

    def handle(self, *args, **options):
        asyncio.run(main(options["infile"]))
