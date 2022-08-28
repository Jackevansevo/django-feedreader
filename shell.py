# flake8: noqa
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
from lxml import etree
import httpx
import listparser
from bs4 import BeautifulSoup
from celery import chain, group, result
from django.contrib.auth.models import User
from django.test import Client
from eventlet.green.urllib.request import Request, urlopen

import feeds.parser as parser
import feeds.tasks as tasks
from feeds.models import *
from feeds.views import *

user = User.objects.first()
c = Client()

with open("inoreader.xml") as f:
    parsed = listparser.parse(f.read())
    urls = [feed.url for feed in parsed.feeds]
