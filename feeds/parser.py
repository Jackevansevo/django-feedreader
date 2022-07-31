from urllib.parse import urlparse

import feedparser
from bs4 import BeautifulSoup
from dateutil import parser
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify
from unidecode import unidecode

from feeds.models import Entry


def parse_feed(resp):
    parsed = feedparser.parse(resp["body"])

    feed = {"last_checked": timezone.now(), "url": resp["url"]}

    if parsed.feed.link == "":
        parsed.feed.link = resp["url"]

    feed["link"] = parsed.feed.link

    if parsed.feed.title != "":
        feed["title"] = parsed.feed.title
    else:
        feed["title"] = urlparse(parsed.feed.link).netloc.lstrip("www.")

    if subtitle := parsed.feed.get("subtitle"):
        if subtitle != "":
            feed["subtitle"] = subtitle

    # https://feedparser.readthedocs.io/en/latest/http-etag.html

    headers = resp["headers"]

    if headers.get("etag"):
        feed["etag"] = headers["etag"]
    if headers.get("last-modified"):
        feed["last_modified"] = parser.parse(headers["last-modified"])

    return feed, parsed.entries


def parse_feed_entry(entry, feed):

    # TODO move this code into some parsing logic
    if hasattr(entry, "content"):
        content = entry.content[0]["value"]
    else:
        content = None

    summary = entry.get("summary")

    if content is None and summary is not None:
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

    title = entry.title
    if title == "":
        # TODO Script any html from this
        title = strip_tags(content[:300])

    feed_parsed = urlparse(feed.url)

    thumbnail = None

    if content is not None:
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
        slug=slugify(unidecode(title)),
        link=entry.link,
        published=published,
        updated=updated,
        content=content,
        author=entry.author if hasattr(entry, "author") else None,
        summary=summary,
        guid=guid,
    )
