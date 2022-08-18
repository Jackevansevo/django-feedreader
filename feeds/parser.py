import logging
from PIL import Image
import re
import posixpath
from urllib.parse import urljoin, urlparse
from datetime import datetime

import httpx
import bleach
import feedparser
import dateutil.parser
from bs4 import BeautifulSoup
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
        if not parsed.path.endswith("/feed"):
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
    # Some links might be empty
    favicons = []
    for favicon_link in soup.findAll("link", {"rel": re.compile(r".*icon.*")}):
        if favicon_link is not None and favicon_link.get("href"):
            favicons.append(urljoin(base_url, favicon_link["href"]))
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

    if resp.headers.get("cross-origin-resource-policy") == "same-origin":
        return

    try:
        Image.open(resp)
    except Exception as err:
        logger.error("failed to parse favicon img: {}".format(err))
        return

    return str(resp.url)


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
    if not url.endswith(".xml") and "html" in resp["headers"].get("content-type"):
        logger.info("{} returned HTML response".format(url))
        html_resp = resp
        # TODO should we prefer atom over rss? What if they find both?
        soup = BeautifulSoup(resp["body"], features="html.parser")

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

    if html_resp is None:
        # Query the parent path i.e: site.com/blog/index.xml -> site.com/blog
        task = tasks.fetch_feed.delay(posixpath.dirname(url.rstrip("/")))
        html_resp = task.get()
        # If this isn't found then query the base_url: site.com/feed -> site.com
        if html_resp["status"] != 200:
            task = tasks.fetch_feed.delay(base_url)
            html_resp = task.get()

        # TODO We probably want to actually find the favicons in the HTML
        # response here, else recurse further up the tree, example:
        # https://eev.ee/feeds/blog.atom.xml -> is the feed
        # https://eev.ee/feeds/ -> is the parent of the feed (would usually contain the favicon but doesn't)
        # https://eev.ee -> is the actually location of the favicon

    # TODO we probably want to actually download the favicon ourselves to avoid
    # cross-origin-resource-policy restrictions

    soup = BeautifulSoup(html_resp["body"], features="html.parser")

    for favicon_loc in find_favicons(html_resp["url"], soup):
        logger.info("Found favicon in page body for {}".format(url))
        if favicon_loc.startswith("http"):
            favicon = check_favicon(favicon_loc)
            if favicon is not None:
                break

    # TODO If html parsing has worked properly, we should never end up here
    if favicon is None:
        for extension in ("favicon.ico", "favicon.png"):
            favicon_loc = posixpath.join(base_url, extension)
            logger.info(
                "No favicon found in page body for {}, will try {}".format(
                    html_resp["url"], favicon_loc
                )
            )
            favicon = check_favicon(favicon_loc)
            if favicon is not None:
                break

    resp["favicon"] = favicon

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

    base_url = urlparse(resp["url"])._replace(path="").geturl()

    link = parsed.feed.get("link")
    if link:
        u = urlparse(link)
        # Remove any query params, and double slashes
        sanitised = u._replace(query="", path=(u.path.replace("//", "/"))).geturl()
        # Ignore if the link is the same as the feed
        # we need the link to the parent site
        if sanitised != resp["url"]:
            # Will handle absolute or relative paths
            feed["link"] = urljoin(base_url, sanitised)
        else:
            feed["link"] = posixpath.dirname(sanitised)
    else:
        feed["link"] = base_url

    title = parsed.feed.get("title")
    if title:
        feed["title"] = title
    else:
        feed["title"] = base_url.lstrip("www.")

    if subtitle := parsed.feed.get("subtitle"):
        if subtitle != "":
            feed["subtitle"] = subtitle

    # https://feedparser.readthedocs.io/en/latest/http-etag.html

    headers = resp["headers"]

    slug = slugify(unidecode(feed["title"]))
    if slug == "":
        slug = slugify(base_url)

    feed["slug"] = slug
    feed["favicon"] = resp.get("favicon")

    if headers.get("etag"):
        feed["etag"] = headers["etag"]
    if headers.get("last-modified"):
        feed["last_modified"] = dateutil.parser.parse(headers["last-modified"])

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

    slug = None
    if title:
        slug = slugify(unidecode(title))

    if not slug:
        if hasattr(entry, "link"):
            slug = slugify(urlparse(entry.link).path)
        else:
            return None

    if not title:
        # TODO Strip any html from this, or figure out a better mechanism to
        # have blank titles
        # Example feed https://justtesting.org/rss
        title = strip_tags(content[:300])

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
            published = dateutil.parser.parse(entry.published)
        except dateutil.parser.ParserError:
            try:
                published = datetime.strptime(entry["published"], "%d %b %Y %Z")
            except ValueError:
                return None

    updated = None
    if hasattr(entry, "updated"):
        try:
            updated = dateutil.parser.parse(entry.updated)
        except dateutil.parser.ParserError:
            try:
                updated = datetime.strptime(entry["updated"], "%d %b %Y %Z")
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
        link=urljoin(feed.link, entry.link) if hasattr(entry, "link") else None,
        published=published,
        updated=updated,
        content=content,
        author=entry.author if hasattr(entry, "author") else None,
        summary=summary,
        guid=guid,
    )
