# flake8: noqa
import feedparser
import listparser
from bs4 import BeautifulSoup
from celery import group, result, chain
from django.contrib.auth.models import User
from django.test import Client
from eventlet.green.urllib.request import Request, urlopen
from urllib.parse import urlparse, urljoin

from feeds.models import *
from feeds.views import *
import feeds.tasks as tasks
import feeds.parser as parser

c = Client()

with open("inoreader.xml") as f:
    parsed = listparser.parse(f.read())
    urls = [feed.url for feed in parsed.feeds]
