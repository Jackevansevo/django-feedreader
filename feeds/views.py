import logging
import uuid
from typing import List

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Exists, OuterRef
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView, DeleteView

import feeds.crawler as crawler
import feeds.parser as parser

from .forms import CategoryForm, SignUpForm, SubscriptionForm
from .models import Category, Entry, Feed, Subscription

# TODO Mechanism to all the subtasks status from a parent tasks
# Or task status for multiple tasks

logger = logging.getLogger(__name__)


def subscriptions_by_category(request: HttpRequest):
    if request.user.is_authenticated:
        subscriptions = (
            Subscription.objects.select_related("category", "feed")
            .filter(user=request.user)
            .order_by("category__name", "feed__title")
        )

        return {"all_subscriptions": subscriptions}
    return {}


def profile(request):
    return render(request, "profile.html")


@login_required
def search(request: HttpRequest):
    search_term = request.GET.get("q")
    entries = Entry.objects.prefetch_related("feed__subscriptions").filter(
        title__icontains=search_term, feed__subscriptions__user=request.user
    )[:100]
    subscriptions = Subscription.objects.select_related("feed").filter(
        feed__title__icontains=search_term, user=request.user
    )[:100]
    return render(
        request,
        "feeds/search.html",
        {"entries": entries, "subscriptions": subscriptions},
    )


@login_required
def export_opml_feeds(request: HttpRequest) -> HttpResponse:
    subscriptions = (
        Subscription.objects.values(
            "feed__url", "feed__link", "category__name", "feed__title", "feed__subtitle"
        )
        .filter(user=request.user)
        .order_by("category__name", "feed__link")
    )
    return render(
        request,
        "feeds/export_feeds.xml",
        {"subscriptions": subscriptions},
        content_type="text/xml",
    )


class SignUpFormView(CreateView):
    template_name = "sign_up.html"
    form_class = SignUpForm
    success_url = settings.LOGIN_URL


class CategoryDetail(DetailView, LoginRequiredMixin):
    model = Category

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user)


class CategoryDeleteView(DeleteView, LoginRequiredMixin):
    model = Category
    success_url = reverse_lazy("feeds:category-list")

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user)

    def form_valid(self, form):
        messages.warning(self.request, f"Deleted: '{self.object}'")
        return super().form_valid(form)


@login_required
def category_list(request: HttpRequest) -> HttpResponse:
    categories = Category.objects.filter(user=request.user).annotate(
        Count("subscriptions")
    )
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.instance.user = request.user
            try:
                form.save()
            except IntegrityError:
                form.add_error("name", "Category already exists")
    else:
        form = CategoryForm()

    return render(
        request,
        "feeds/category_form.html",
        {"form": form, "categories": categories},
    )


@login_required
def index(request: HttpRequest) -> HttpResponse:
    entries = Entry.objects.select_related("feed").filter(
        feed__subscriptions__user=request.user, published__lte=timezone.now()
    )
    paginator = Paginator(entries, 50)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return render(request, "feeds/index.html", {"page_obj": page_obj})


@login_required
def feed_list(request: HttpRequest) -> HttpResponse:
    subscriptions = (
        Subscription.objects.select_related("feed", "user", "category")
        .filter(user=request.user)
        .order_by("feed__title")
    )
    return render(request, "feeds/feed_list.html", {"subscriptions": subscriptions})


@login_required
def feed_detail(request: HttpRequest, feed_slug: str) -> HttpResponse:

    # TODO Can this be done in a single query?

    queryset = Feed.objects.annotate(
        subscribed=Exists(Subscription.objects.filter(feed=OuterRef("pk")))
    )

    feed = get_object_or_404(queryset, slug=feed_slug)

    if feed.subscribed:
        subscription = Subscription.objects.get(feed=feed, user=request.user)

    return render(
        request,
        "feeds/feed_detail.html",
        {
            "subscription": subscription if feed.subscribed else None,
            "feed": feed,
        },
    )


@login_required
def entry_detail(
    request: HttpRequest, feed_slug: str, uuid: uuid.UUID, entry_slug: str
) -> HttpResponse:
    entry = get_object_or_404(
        Entry,
        slug=entry_slug,
        uuid=uuid,
        feed__slug=feed_slug,
    )
    return render(request, "feeds/entry_detail.html", {"entry": entry})


@login_required
def discover(request: HttpRequest) -> HttpResponse:
    search_term = request.GET.get("q")
    feeds: List[Feed] = []

    if search_term:
        # TODO better way to determine if search_term is possible URL?
        if " " not in search_term and "." in search_term:
            if not search_term.startswith("http"):
                search_term = "http://" + search_term
            is_url = parser.is_valid_url(search_term)
        else:
            is_url = False

        logger.info("Search term: {} is url {}".format(search_term, is_url))

        feeds = []

        if is_url:
            try:
                feed = (
                    Feed.objects.prefetch_related("entries")
                    .annotate(
                        subscribed=Exists(
                            Subscription.objects.filter(
                                feed=OuterRef("pk"), user=request.user
                            )
                        ),
                    )
                    .get(url__icontains=parser.strip_scheme(search_term))
                )
            except Feed.DoesNotExist:
                logger.info("Crawling web for {}".format(search_term))
                try:
                    sync_crawl_url = async_to_sync(crawler.crawl)
                    resp, parsed, favicon = sync_crawl_url(search_term)
                    if resp is not None:
                        logger.info("Parsing resp: {}".format(search_term))
                        feed = crawler.ingest_feed(resp, parsed, favicon)
                        logger.info("Parsed: {}".format(search_term))
                        if feed is not None:
                            feeds = [feed]
                except Exception as exc:
                    if settings.DEBUG:
                        raise
                    messages.error(request, str(exc))
            else:
                logger.info("Found pre-existing feed for {}".format(search_term))
                feeds = [feed]
        else:
            # First attempt to lookup pre-existing/similar feeds
            search_for = parser.strip_scheme(search_term) if is_url else search_term
            feeds = (
                Feed.objects.prefetch_related("entries")
                .annotate(
                    subscribed=Exists(
                        Subscription.objects.filter(
                            feed=OuterRef("pk"), user=request.user
                        )
                    ),
                )
                .filter(title__icontains=search_for, url__icontains=search_for)
            )
            if feeds:
                logger.info("Found existing matches for: '{}'".format(search_term))

    return render(request, "feeds/discover.html", {"feeds": feeds})


def feed_follow(request, feed_slug):
    feed = get_object_or_404(Feed, slug=feed_slug)
    if request.method == "POST":
        form = SubscriptionForm(request.POST)
        if form.is_valid():
            form.instance.user = request.user
            form.save()
            return redirect(feed)
    else:
        form = SubscriptionForm(initial={"feed": feed.pk})
    return render(request, "feeds/follow.html", {"feed": feed, "form": form})


class SubscriptionDeleteView(DeleteView, LoginRequiredMixin):
    model = Subscription
    success_url = reverse_lazy("feeds:feed-list")

    def get_queryset(self):
        return Subscription.objects.filter(user=self.request.user)

    def form_valid(self, form):
        messages.warning(self.request, f"Unsubscribed from: '{self.object.feed}'")
        return super().form_valid(form)
