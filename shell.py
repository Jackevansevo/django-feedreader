# flake8: noqa
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse

from lxml import etree
import httpx
import listparser
from bs4 import BeautifulSoup
from django.contrib.auth.models import User
from django.test import Client

import feeds.parser as parser
from feeds.models import *
from feeds.views import *

user = User.objects.first()
c = Client()
