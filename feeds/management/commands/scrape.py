import argparse
import asyncio
import sys
from urllib.parse import urlparse

import httpx
import listparser
from django.core.management.base import BaseCommand

USER_AGENT = "feedreader/1 +https://github.com/Jackevansevo/feedreader/"


async def crawl_url(client, url):
    print("fetching:", url)

    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
    except Exception:
        return

    if resp.status_code != 200:
        print("ignoring", resp, "got response:", resp.status_code)
        return

    content_headers = resp.headers.get("content-type")

    if content_headers is not None:
        if "html" in content_headers or "json" in content_headers:
            print("ignoring", resp, "got", content_headers, "in headers")
            return

    path = urlparse(str(resp.url)).netloc

    print("writing", path)
    f = open("examples/" + path, "wb")
    f.write(resp.content)


async def main(infile):

    parsed = listparser.parse(infile.read())

    timeout = httpx.Timeout(10.0, connect=60.0)
    limits = httpx.Limits(
        max_keepalive_connections=None, max_connections=None, keepalive_expiry=10
    )

    async with httpx.AsyncClient(
        timeout=timeout, limits=limits, follow_redirects=True
    ) as client:
        await asyncio.gather(
            *[
                asyncio.ensure_future(crawl_url(client, feed["url"]))
                for feed in parsed["feeds"]
            ],
        )


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "infile", nargs="?", type=argparse.FileType("r"), default=sys.stdin
        )

    def handle(self, *args, **options):
        asyncio.run(main(options["infile"]))
