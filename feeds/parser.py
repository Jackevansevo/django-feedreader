from bs4 import BeautifulSoup
from dateutil import parser
from django.utils import timezone
from django.utils.text import slugify
from unidecode import unidecode
from urllib.parse import urlparse
import feedparser
from feeds.models import Entry


def parse_feed(resp):

    # TODO we probably want to move some of this logic into a separate parser
    # file and consolidate with Feed.from_feed_entry

    # TODO would it be possible just to build an in memory version of Feed / Entry and return it from this function
    # Then any data integrity issues would be solved when calling .save() ?

    # We also want updates to be efficient as well???

    if resp["status"] == 304:
        # Nothing to update
        return None, None

    parsed = feedparser.parse(resp["body"])

    feed = {"last_checked": timezone.now(), "url": resp["url"]}

    if parsed.feed.link == "":
        parsed.feed.link = resp["url"]

    feed["link"] = parsed.feed.link

    if parsed.feed.title != "":
        feed["title"] = parsed.feed.title
    else:
        feed["title"] = urlparse(parsed.feed.link).netloc.lstrip("www.")

    # https://feedparser.readthedocs.io/en/latest/http-etag.html

    headers = resp["headers"]

    if headers.get("etag"):
        feed["etag"] = headers["etag"]
    if headers.get("last-modified"):
        feed["last_modified"] = parser.parse(headers["last-modified"])

    return feed, parsed.entries


def parse_feed_entry(entry, feed):

    # TODO move this code into some parsing logic
    content = entry.get("content")
    if content is not None:
        content = content[0]["value"]

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

    published = entry.get("published")
    if published is not None:
        try:
            published = parser.parse(published)
        except ValueError:
            return None

    updated = entry.get("updated")
    if updated is not None:
        try:
            updated = parser.parse(updated)
        except ValueError:
            return None

    if published is None and updated is not None:
        # Just for sorting
        published = updated

    title = entry["title"]

    return Entry(
        feed=feed,
        thumbnail=thumbnail,
        title=entry["title"],
        slug=slugify(unidecode(title)),
        link=entry["link"],
        published=published,
        updated=updated,
        content=content,
        author=entry.get("author"),
        summary=summary,
        guid=entry.get("guid"),
    )
