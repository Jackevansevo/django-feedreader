# flake8: noqa
import feedparser
import listparser
from bs4 import BeautifulSoup
from celery import group, result, chain
from django.contrib.auth.models import User
from django.test import Client
from eventlet.green.urllib.request import Request, urlopen

from feeds.models import *
from feeds.tasks import *

c = Client()

with open("inoreader.xml") as f:
    parsed = listparser.parse(f.read())
    urls = [feed.url for feed in parsed.feeds]
