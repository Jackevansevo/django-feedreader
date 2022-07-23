# flake8: noqa
import feedparser
from bs4 import BeautifulSoup
from celery import group, result
from django.contrib.auth.models import User
from django.test import Client
from eventlet.green.urllib.request import Request, urlopen

from feeds.models import *
from feeds.tasks import *

c = Client()
