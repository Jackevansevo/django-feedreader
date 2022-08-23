import os
import io
from lxml import etree

import logging
import re
import posixpath
from urllib.parse import urljoin, urlparse
from datetime import datetime
from django.core.files.images import ImageFile

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


# TODO: I think there would be some benefits to rewriting this all to be async
# because there's a lot of blocking network calls but I'm not sure how this
# would be compatible with celery jobs


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


def parse(resp):
    # Would it be better to dispatch to child classes via Parser instead of
    # returning the child class?
    parser = Parser(resp)
    if parser.root.tag == "rss":
        return RSSParser(resp)
    elif parser.root.tag.endswith("feed"):
        return AtomParser(resp)
    elif parser.root.tag.endswith("RDF"):
        return RDFParser(resp)


class Parser:

    # TODO Can namespace stuff be avoided?

    # TODO Test against a wide variety of inputs

    # This should just be a convenient mechanism to query for data in RSS/XML
    # that's feed type agnostic.

    # TODO Hopefully there won't be any issues between versions????

    def __init__(self, content):
        xml_parser = etree.XMLParser(recover=True)
        self.et = etree.parse(io.BytesIO(content), parser=xml_parser)
        self.root = self.et.getroot()
        self.nsmap = self.root.nsmap

    def subtitle(self):
        # Alias for subtitle
        return self.description()


def parse_author_text(text):
    try:
        email, name = text.split(" ", maxsplit=1)
    except ValueError:
        # TODO Should we validate check this is an email and not a name?
        return {"email": text}
    else:
        return {"name": name, "email": email}


class RSSParser(Parser):
    def __init__(self, content):
        self.type = "rss"
        super().__init__(content)
        self.channel = self.et.find("channel", namespaces=self.nsmap)

    def title(self):
        return self.channel.findtext("title", namespaces=self.nsmap)

    def description(self):
        return self.et.channel.findtext("description", namespaces=self.nsmap)

    def author(self):
        author = {}

        if "itunes" in self.nsmap:
            itunes_tag = self.channel.find("itunes:owner", namespaces=self.nsmap)
            if itunes_tag is not None:
                name_text = itunes_tag.findtext("itunes:name", namespaces=self.nsmap)
                if name_text:
                    author["name"] = name_text

                email_text = itunes_tag.findtext("itunes:email", namespaces=self.nsmap)
                if email_text:
                    author["email"] = email_text

                return author

        if self.root.get("version") == "2.0":
            managing_editor_text = self.channel.findtext(
                "managingEditor", namespaces=self.nsmap
            )
            if managing_editor_text:
                return parse_author_text(managing_editor_text)

        return

    def link(self):
        return self.channel.findtext("link", namespaces=self.nsmap)

    def _parse_entry(self, raw_entry):
        entry = {}
        for element in raw_entry:
            match element.tag:
                case "title" | "guid" | "description" | "pubDate" | "link":
                    entry[element.tag] = element.text
                case _:
                    if "content" in element.tag:
                        entry["content"] = element.text

        return entry

    def entries(self):
        return [
            self._parse_entry(entry)
            for entry in self.channel.iterfind("item", namespaces=self.nsmap)
        ]


class AtomParser(Parser):
    def __init__(self, content):
        self.type = "atom"
        super().__init__(content)

    def title(self):
        return self.et.findtext("title", namespaces=self.nsmap)

    def description(self):
        return self.et.findtext("subtitle", namespaces=self.nsmap)

    def author(self):

        author = {}

        author_tag = self.et.find("author", namespaces=self.nsmap)

        if author_tag is not None:
            name_text = author_tag.findtext("name", namespaces=self.nsmap)
            if name_text:
                author["name"] = name_text

            email_text = author_tag.findtext("email", namespaces=self.nsmap)
            if email_text:
                author["email"] = email_text

            return author

    def link(self):
        links = self.et.findall("link", namespaces=self.nsmap)

        # TODO would it be better to build a dictionary here?

        for link in links:
            # Return the best matching link
            if link.get("rel") == "alternate" and link.get("type") == "text/html":
                return link.get("href")

        for link in links:
            if link.get("rel") == "alternate":
                return link.get("href")

        for link in links:
            if link.get("rel") == "self" or link.get("rel") == "hub":
                continue

            href = link.get("href")
            if href is not None:
                return href
            else:
                return link.text

        id_text = self.et.findtext("id", namespaces=self.nsmap)
        if id_text is not None and is_valid_url(id_text):
            return id_text

    def _parse_entry(self, raw_entry):
        entry = {}
        for element in raw_entry:
            # TODO This is awful: Figure out how to deal with weird namespace
            # prefix '{http://www.w3.org/2005/Atom}title'
            if "}" in element.tag:
                tag = element.tag.split("}")[0]
            else:
                tag = element.tag

            match tag:
                case "title" | "guid" | "description" | "updated" | "id":
                    entry[element.tag] = element.text
                case "link":
                    entry[element.tag] = element.get("href")
                case _:
                    if "content" in element.tag:
                        entry["content"] = element.text

        return entry

    def entries(self):
        return [
            self._parse_entry(entry)
            for entry in self.et.iterfind("entry", namespaces=self.nsmap)
        ]


class RDFParser(RSSParser):
    def __init__(self, content):
        self.type = "rdf"
        super().__init__(content)

    def author(self):
        if self.nsmap.get("dc") == "http://purl.org/dc/elements/1.1/":
            creator_text = self.channel.findtext("dc:creator", namespaces=self.nsmap)
            if creator_text:
                return parse_author_text(creator_text)


def get_feed_link(url, links):
    for link in links:
        if link.get("rel") == "alternate" and link.get("type") == "text/html":
            return urljoin(url, link.get("href"))

    for link in links:
        return urljoin(url, link.get("href"))


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

    # TODO Custom parser maybe????

    parser = parse(resp["body"])

    if html_resp is None:

        parsed_links = parser.links()
        # Use the most appropriate link
        link = get_feed_link(resp["url"], parsed_links)
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
