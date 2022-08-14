import logging
import re
from urllib.parse import urljoin, urlparse

import bleach
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify
from unidecode import unidecode

import feeds.tasks as tasks
from feeds.models import Entry, Feed

BLEACH_ALLOWED_TAGS = [
    "a",
    "abbr",
    "acronym",
    "address",
    "article",
    "aside",
    "audio",
    "b",
    "blockquote",
    "blockquote",
    "br",
    "caption",
    "center",
    "cite",
    "code",
    "col",
    "colgroup",
    "del",
    "details",
    "div",
    "dl",
    "dt",
    "em",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "span",
    "strike",
    "strong",
    "table",
    "tbody",
    "th",
    "thead",
    "tr",
    "ul",
    "video",
]


logger = logging.getLogger(__name__)


def strip_scheme(url):
    parsed = urlparse(url)
    scheme = "%s://" % parsed.scheme
    return parsed.geturl().replace(scheme, "", 1)


def is_valid_url(query: str):
    url_validator = URLValidator()
    try:
        url_validator(query)
    except ValidationError:
        return False
    else:
        return True


def find_common_feed_urls(url):
    parsed = urlparse(url)

    if parsed.netloc.endswith("wordpress.com") or parsed.netloc.endswith(
        "bearblog.dev"
    ):
        if not parsed.path.rstrip("/").endswith("/feed"):
            return parsed._replace(path=f"{parsed.path}/feed/").geturl()
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


def crawl_url(url: str):
    task = tasks.fetch_feed.delay(find_common_feed_urls(url))
    resp = task.get()

    if "html" in resp["headers"].get("content-type"):
        logger.info("{} returned HTML response".format(url))
        # TODO should we prefer atom over rss? What if they find both?
        soup = BeautifulSoup(resp["body"], features="html.parser")

        rss_link = soup.find(
            "link", {"type": re.compile(r"application\/(atom|rss)\+xml$")}
        )

        if rss_link is None:
            rss_link = soup.find("a", string=re.compile("rss", re.I))

        if rss_link is None:
            rss_link = soup.find(
                "a", {"href": re.compile(r"(index|feed|rss|atom).*.xml$")}
            )

        if rss_link is None:
            rss_link = soup.find("a", {"href": re.compile(r".*(rss|atom)$")})

        if rss_link is not None:
            logger.info("Found feed link in page body for {}".format(url))
            url = urljoin(url, rss_link["href"])
            logger.info("Crawling {}".format(url))
            task = tasks.fetch_feed.delay(url)
            resp = task.get()
        else:
            logger.info("No feed link in page body for {}".format(url))

            logger.info("Crawling common extensions for {}".format(url))

            common_extensions = (
                "feed.xml",
                "index.xml",
                "rss.xml",
                "rss",
                "atom.xml",
                "atom",
                "feed.atom",
            )

            possible_locations = []

            # TODO: clean up
            rel_path = url
            if not url.endswith("/"):
                rel_path += "/"
            for extention in common_extensions:
                possible_locations.append(urljoin(rel_path, extention))

            parsed_url = urlparse(url)
            if parsed_url.path != "":
                base_url = parsed_url._replace(path="").geturl()
                for extention in common_extensions:
                    possible_locations.append(urljoin(base_url, extention))

            for loc in possible_locations:
                logger.info("Trying {}".format(loc))
                task = tasks.fetch_feed.delay(loc)
                resp = task.get()
                if resp["status"] != 404:
                    break

    return resp


@transaction.atomic
def ingest_feed(resp, url):
    parsed, entries = parse_feed(resp)

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
        for entry in (parse_feed_entry(entry, feed) for entry in entries)
        if entry is not None
    )
    return feed


def parse_feed(resp):
    parsed = feedparser.parse(resp["body"])

    if parsed.entries == []:
        return None, None

    feed = {"last_checked": timezone.now(), "url": resp["url"]}

    base_url = urlparse(resp["url"])

    link = parsed.feed.get("link")
    if link and link != "/":
        feed["link"] = link
    else:
        feed["link"] = base_url

    title = parsed.feed.get("title")
    if title:
        feed["title"] = title
    else:
        feed["title"] = base_url.netloc.lstrip("www.")

    if subtitle := parsed.feed.get("subtitle"):
        if subtitle != "":
            feed["subtitle"] = subtitle

    # https://feedparser.readthedocs.io/en/latest/http-etag.html

    headers = resp["headers"]

    slug = slugify(unidecode(feed["title"]))
    if slug == "":
        slug = slugify(base_url)

    feed["slug"] = slug

    if headers.get("etag"):
        feed["etag"] = headers["etag"]
    if headers.get("last-modified"):
        feed["last_modified"] = parser.parse(headers["last-modified"])

    return feed, parsed.entries


def parse_feed_entry(entry, feed):

    if hasattr(entry, "content"):
        content = entry.content[0]["value"]
    else:
        content = None

    summary = entry.get("summary")

    if not content and not summary:
        return None

    if not content and summary:
        content = summary
        summary = None
    elif summary == content:
        summary = None

    if summary is not None:
        # Strip out any images
        soup = BeautifulSoup(summary, features="html.parser")
        for img in soup.findAll("img"):
            img.extract()

        # Strip out any continue reading links
        for a_tag in soup.findAll("a"):
            if "continue reading" in a_tag.text.lower():
                a_tag.extract()

        summary = str(soup)

    title = entry.get("title")

    if title:
        slug = slugify(unidecode(title))
    else:
        # TODO Strip any html from this, or figure out a better mechanism to
        # have blank titles
        # Example feed https://justtesting.org/rss
        title = strip_tags(content[:300])

    if slug == "":
        if hasattr(entry, "link"):
            slug = slugify(urlparse(entry.link).path)
        else:
            return None

    feed_parsed = urlparse(feed.url)

    thumbnail = None

    if content is not None:
        content = bleach.clean(
            content,
            attributes=["href", "title", "src"],
            tags=BLEACH_ALLOWED_TAGS,
            strip=True,
        )
        soup = BeautifulSoup(content, features="html.parser")

        for img in soup.findAll("img"):
            del img["width"]
            del img["height"]
            del img["class"]

            src = img.get("src")
            parsed_src = urlparse(src)

            # Some feeds still use relative URLs, we can attempt to fix this
            if parsed_src.netloc == "":
                img["src"] = parsed_src._replace(
                    netloc=feed_parsed.netloc, scheme=feed_parsed.scheme
                ).geturl()

            img["class"] = "rounded mx-auto d-block"

            # TODO use the biggest image as the thumbnail
            if thumbnail is None:
                src = img.get("src")
                if src is not None and len(src) < 500:
                    thumbnail = src

        content = str(soup)

    published = None
    if hasattr(entry, "published"):
        try:
            published = parser.parse(entry.published)
        except ValueError:
            return None

    updated = None
    if hasattr(entry, "updated"):
        try:
            updated = parser.parse(entry.updated)
        except ValueError:
            return None

    if published is None and updated is not None:
        # Just for sorting
        published = updated

    guid = None
    if hasattr(entry, "guid"):
        if not (hasattr(entry, "guidislink") and entry.guidislink):
            guid = entry.guid

    return Entry(
        feed=feed,
        thumbnail=thumbnail,
        title=title,
        slug=slug,
        link=entry.link if hasattr(entry, "link") else None,
        published=published,
        updated=updated,
        content=content,
        author=entry.author if hasattr(entry, "author") else None,
        summary=summary,
        guid=guid,
    )
