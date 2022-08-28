import io
import posixpath
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import bleach
import dateutil.parser
import httpx
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils import timezone
from django.utils.text import slugify
from lxml import etree
from unidecode import unidecode

import feeds.tasks as tasks
from feeds.models import Entry

XML_PARSER = etree.XMLParser(recover=True, remove_comments=True)


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


class ParseException(Exception):
    pass


def parse(f):

    if isinstance(f, str) and is_valid_url(f):
        resp = httpx.get(
            f, follow_redirects=True, headers={"User-Agent": tasks.USER_AGENT}
        )
        f = io.BytesIO(resp.content)

    et = etree.parse(f, parser=XML_PARSER)

    root = et.getroot()

    if root is None:
        raise ParseException("missing root tag")

    if "}" in root.tag:
        root_tag = root.tag.split("}")[1]
    else:
        root_tag = root.tag

    match root_tag:
        case "rss":
            parser = RSSParser(et)
        case "RDF":
            parser = RDFParser(et)
        case "feed":
            parser = AtomParser(et)
        case _:
            raise NotImplemented

    # TODO Do we want to save some of these attributes in slots in a class
    attributes = {
        "link": parser.link(),
        "title": parser.title(),
        "subtitle": parser.description(),
        "author": parser.author(),
        "entries": parser.entries(),
    }

    if isinstance(parser, RSSParser):
        ttl = parser.ttl()
        if ttl is not None:
            attributes["ttl"] = ttl

    return attributes


def parse_author_text(text):
    try:
        email, name = text.split(" ", maxsplit=1)
    except ValueError:
        # TODO Should we validate check this is an email and not a name?
        return {"email": text}
    else:
        return {"name": name, "email": email}


class RSSParser:
    def __init__(self, et):
        self.et = et
        self.root = self.et.getroot()
        self.nsmap = self.root.nsmap
        self.channel = self.et.find("channel", namespaces=self.nsmap)

    def title(self):
        return self.channel.findtext("title", namespaces=self.nsmap)

    def description(self):
        return self.channel.findtext("description", namespaces=self.nsmap)

    def ttl(self):
        ttl = self.channel.findtext("ttl", namespaces=self.nsmap)
        if ttl is not None:
            return timedelta(minutes=int(ttl))

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
                case "title" | "guid" | "link" | "content":
                    entry[element.tag] = element.text
                case "pubDate":
                    entry["published"] = element.text
                case "description":
                    entry["summary"] = element.text
                case _:
                    if element.prefix == "content":
                        entry["content"] = element.text

        return entry

    def entries(self):
        return [
            self._parse_entry(entry)
            for entry in self.channel.iterfind("item", namespaces=self.nsmap)
        ]


class AtomParser:
    def __init__(self, et):
        self.et = et
        self.root = self.et.getroot()
        self.nsmap = self.root.nsmap

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
                tag = element.tag.split("}")[1]
            else:
                tag = element.tag

            match tag:
                case "title" | "guid" | "updated" | "id" | "published" | "updated" | "summary":
                    entry[tag] = element.text
                case "link":
                    entry[tag] = element.get("href")
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
    def __init__(self, et):
        super().__init__(et)

    def author(self):
        if self.nsmap.get("dc") == "http://purl.org/dc/elements/1.1/":
            creator_text = self.channel.findtext("dc:creator", namespaces=self.nsmap)
            if creator_text:
                return parse_author_text(creator_text)


def parse_feed(resp, parsed, favicon):

    if parsed["entries"] == []:
        return None, None

    feed = {"last_checked": timezone.now(), "url": str(resp.url)}

    base_url = urlparse(str(resp.url))._replace(path="").geturl()

    link = parsed.get("link")
    if link:
        u = urlparse(link)
        # Remove any query params, and double slashes
        sanitised = u._replace(query="", path=(u.path.replace("//", "/"))).geturl()
        # Ignore if the link is the same as the feed
        # we need the link to the parent site
        if sanitised != resp.url:
            # Will handle absolute or relative paths
            feed["link"] = urljoin(base_url, sanitised)
        else:
            feed["link"] = posixpath.dirname(sanitised)
    else:
        feed["link"] = base_url

    title = parsed.get("title")
    if title:
        feed["title"] = title
    else:
        feed["title"] = base_url.lstrip("www.")

    if subtitle := parsed.get("subtitle"):
        if subtitle != "":
            feed["subtitle"] = subtitle

    headers = resp.headers

    slug = slugify(unidecode(feed["title"]))
    if slug == "":
        slug = slugify(base_url)

    feed["slug"] = slug
    feed["favicon"] = favicon

    if headers.get("etag"):
        feed["etag"] = headers["etag"]
    if headers.get("last-modified"):
        feed["last_modified"] = dateutil.parser.parse(headers["last-modified"])

    return feed, parsed["entries"]


def parse_feed_entry(entry, feed):

    # TODO update parse to parse descriptions and publish dates properly

    content = entry.get("content")
    summary = entry.get("summary")

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

    if not title:
        if entry.get("link"):
            title = unidecode(urlparse(entry["link"]).path)
        else:
            title = content[:50]

    slug = slugify(unidecode(title))
    if not slug:
        path = urlparse(entry.get("link")).path.rstrip("/")
        if path:
            slug = posixpath.basename(path)

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
    if entry.get("published"):
        try:
            published = dateutil.parser.parse(entry["published"])
        except dateutil.parser.ParserError:
            try:
                published = datetime.strptime(entry["published"], "%d %b %Y %Z")
            except ValueError:
                return None

    updated = None
    if entry.get("updated"):
        try:
            updated = dateutil.parser.parse(entry["updated"])
        except dateutil.parser.ParserError:
            try:
                updated = datetime.strptime(entry["updated"], "%d %b %Y %Z")
            except ValueError:
                return None

    if published is None and updated is not None:
        # Just for sorting
        published = updated

    guid = None
    if entry.get("guid"):
        guid = entry["guid"]

    return Entry(
        feed=feed,
        thumbnail=thumbnail,
        title=title,
        slug=slug,
        link=urljoin(feed.link, entry["link"]) if entry.get("link") else None,
        published=published,
        updated=updated,
        content=content,
        author=entry["author"] if entry.get("author") else None,
        summary=summary,
        guid=guid,
    )
