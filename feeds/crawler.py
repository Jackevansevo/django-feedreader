import io
import logging
import os
import posixpath
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from django.core.files.images import ImageFile
from django.db import IntegrityError, transaction

import feeds.parser as parser
import feeds.tasks as tasks
from feeds.models import Entry, Feed

logger = logging.getLogger(__name__)


def find_common_feed_urls(url):
    parsed = urlparse(url)

    if parsed.netloc.endswith("wordpress.com") or parsed.netloc.endswith(
        "bearblog.dev"
    ):
        if not parsed.path.rstrip("/").endswith("/feed"):
            return parsed._replace(path=f"{parsed.path.strip('/')}/feed/").geturl()
    elif parsed.netloc.endswith("substack.com"):
        if not parsed.path.endswith("/feed"):
            return parsed._replace(path=f"{parsed.path}/feed").geturl()
    elif parsed.netloc.endswith("tumblr.com"):
        if parsed.path != "/rss":
            return urljoin(url, "rss")
    elif parsed.netloc.endswith("medium.com"):
        if not parsed.path.startswith("/feed"):
            return parsed._replace(path=f"feed{parsed.path}").geturl()
    elif parsed.netloc.endswith("blogspot.com"):
        if parsed.path != "/feeds/posts/default":
            return urljoin(url, "feeds/posts/default")

    return url


def find_favicons(base_url, soup):
    favicons = []

    for favicon_link in soup.findAll(
        "link", {"rel": re.compile(r".*icon.*"), "href": re.compile(r"^(?!data).*$")}
    ):
        logger.info(
            "Found favicon: {} in page body for {}".format(
                favicon_link["href"], base_url
            )
        )
        favicons.append(urljoin(base_url, favicon_link["href"]))

    # Fall back to checking common extensions
    for extension in ("/favicon.ico", "/favicon.png"):
        favicon_loc = urljoin(base_url, extension)
        if favicon_loc not in favicons:
            favicons.append(favicon_loc)

    return favicons


def find_rss_link(soup):
    rss_link = soup.find("link", {"type": re.compile(r"application\/(atom|rss)\+xml$")})

    if rss_link is None:
        rss_link = soup.find("a", string=re.compile("rss", re.I))

    if rss_link is None:
        rss_link = soup.find("a", {"href": re.compile(r"(index|feed|rss|atom).*.xml$")})

    if rss_link is None:
        rss_link = soup.find("a", {"href": re.compile(r".*(rss|atom)$")})

    return rss_link


def find_common_extensions(parsed_url):
    url = parsed_url.geturl()

    common_extensions = (
        "feed.xml",
        "index.xml",
        "rss.xml",
        "feed",
        "rss",
        "atom.xml",
        "atom",
        "feed.atom",
    )

    possible_locations = []

    # If we have a path i.e. site.com/blog check:
    # - site.com/blog/feed
    # - site.com/blog/index.xml
    if parsed_url.path:
        path = parsed_url._replace(path="").geturl()
        for extention in common_extensions:
            possible_locations.append(posixpath.join(path, extention))

    for extention in common_extensions:
        possible_locations.append(posixpath.join(url, extention))

    return possible_locations


def scrape_common_endpoints(parsed_url):
    logger.info("Crawling common extensions for {}".format(parsed_url.geturl()))

    for loc in find_common_extensions(parsed_url):
        logger.info("Trying {}".format(loc))
        task = tasks.fetch_feed.delay(loc)
        resp = task.get()
        if resp["status"] != 404:
            return resp


def check_favicon(path):
    # Verify the favicon exists
    try:
        resp = httpx.get(
            path, follow_redirects=True, headers={"User-Agent": tasks.USER_AGENT}
        )
    except httpx.HTTPError:
        return

    if resp.status_code != 200:
        return

    if "html" in resp.headers["content-type"]:
        return

    parsed = urlparse(str(resp.url))
    _, ext = os.path.splitext(parsed.path)
    return ImageFile(io.BytesIO(resp.read()), name=f"{parsed.netloc}-favicon{ext}")


def crawl_url(url: str):

    # TODO: merge with create_subscription logic, code is duplicated /
    # conflicting across async/sync code

    # The user has either passed in:
    # - A site: i.e. site.com (html)
    # - A feed: i.e. site.com/index.xml (xml)

    # Regardless we'll need to end up scraping both

    # Assumes the user has passed a feed (happy path)
    task = tasks.fetch_feed.delay(find_common_feed_urls(url))
    resp = task.get()

    parsed_url = urlparse(url)
    base_url = parsed_url._replace(path="", query="").geturl()

    favicon = None
    html_resp = None

    # If we acually got back HTML

    # TODO Can we trust headers to be included? Do we need to inspect the contents
    if "html" in resp["headers"].get("content-type"):
        # TODO should we prefer atom over rss? What if they find both?
        # TOOD if this fails the response type is probably not valid HTML ...
        soup = BeautifulSoup(resp["body"], features="html.parser")

        logger.info("{} returned HTML response".format(url))
        html_resp = resp

        rss_link = find_rss_link(soup)

        if rss_link is not None:
            logger.info("Found feed link in page body for {}".format(url))
            url = urljoin(url, rss_link["href"])
            logger.info("Crawling {}".format(url))
            task = tasks.fetch_feed.delay(url)
            resp = task.get()
        else:
            logger.info("No feed link in page body for {}".format(url))

            resp = scrape_common_endpoints(parsed_url)

    # TODO Custom parser maybe????

    parsed = parser.parse(io.BytesIO(resp["body"]))

    if html_resp is None:

        parsed_link = parsed.get("link")
        # Use the most appropriate link
        link = urljoin(resp["url"], parsed_link)
        # Fall back to using the base url:
        # i.e: site.com/blog/index.xml -> site.com/blog/
        if link is None:
            link = posixpath.dirname(url.rstrip("/")) + "/"
            logger.info(
                "No site link found in feed xml, falling back to: {}".format(link)
            )
        else:
            logger.info("Site link found in feed xml: {}".format(link))

        task = tasks.fetch_feed.delay(link)
        html_resp = task.get()
        # If this isn't found then query the base_url: site.com/feed -> site.com
        if html_resp["status"] != 200:
            logger.info("Failed to fetch: {}, reverting to {}".format(link, base_url))
            task = tasks.fetch_feed.delay(base_url)
            html_resp = task.get()

    soup = BeautifulSoup(html_resp["body"], features="html.parser")

    for favicon_loc in find_favicons(html_resp["url"], soup):
        favicon = check_favicon(favicon_loc)
        if favicon is not None:
            break

    resp["favicon"] = favicon

    return resp


@transaction.atomic
def ingest_feed(resp, url):
    parsed, entries = parser.parse_feed(resp)

    if not parsed:
        return None

    try:
        with transaction.atomic():
            feed = Feed.objects.create(**parsed)
    except IntegrityError:
        # The feed potentially already exists
        if resp["url"] != url:
            feed = Feed.objects.get(url=resp["url"])
            return feed
        else:
            raise

    Entry.objects.bulk_create(
        entry
        for entry in (parser.parse_feed_entry(entry, feed) for entry in entries)
        if entry is not None
    )
    return feed
