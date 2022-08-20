import logging
import uuid

import listparser
from celery import group, result
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.postgres.search import SearchVector
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Exists, OuterRef, Q
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotFound,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView, DeleteView

import feeds.parser as parser
import feeds.tasks as tasks

from .forms import CategoryForm, OPMLUploadForm, SignUpForm, SubscriptionForm
from .models import Category, Entry, Feed, Subscription

# TODO Mechanism to all the subtasks status from a parent tasks
# Or task status for multiple tasks

logger = logging.getLogger(__name__)


def subscriptions_by_category(request):
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


def task_status(_, task_id) -> JsonResponse:
    task_result = result.AsyncResult(task_id)
    data = {
        "id": task_id,
        "status": task_result.status,
        "result": task_result.result,
    }
    return JsonResponse(data)


def serialize_child(child):
    # TODO Error 'results' are serializable, not sure if there's a better way TODO this
    if child.status == "FAILURE":
        return {"id": child.id, "status": child.status, "error": str(child.result)}
    return {"id": child.id, "status": child.status, "result": child.result}


def task_group_status(_: HttpRequest, task_id) -> HttpResponse:
    group_result = result.GroupResult.restore(task_id)
    if group_result is None:
        return HttpResponseNotFound(f"GroupResult('{task_id}') not found")
    data = {
        "id": task_id,
        "children": [serialize_child(child) for child in group_result.children],
        "completedCount": group_result.completed_count(),
    }
    return JsonResponse(data)


@login_required
def import_feed_detail(request: HttpRequest, task_id) -> HttpResponse:
    task_meta_data = cache.get(task_id)
    if task_meta_data is None:
        raise Http404
    if task_meta_data["user_id"] != request.user.id:
        raise Http404
    return render(request, "feeds/import_feeds_detail.html", {"data": task_meta_data})


@login_required
def import_opml_feeds(request: HttpRequest) -> HttpResponse:

    is_running = False

    running_job = cache.get(f"{request.user.id}-import")
    # If we've cached a job, check it it's still running, if it is, disable the form
    if running_job:
        group_result = result.GroupResult.restore(running_job)
        if not group_result.ready():
            is_running = True
        else:
            cache.delete(f"{request.user.id}-import")

    if request.method == "POST":
        form = OPMLUploadForm(request.POST, request.FILES)

        if is_running:
            form.add_error("file", "Import task already running")

        elif form.is_valid():
            f = request.FILES["file"]
            contents = f.read()
            parsed = listparser.parse(contents)

            jobs = []
            fetching = []
            skipped = []

            # TODO test this out

            urls = [feed.url for feed in parsed.feeds]

            q = Q(user=request.user)
            for url in urls:
                q |= Q(feed__url__icontains=url)

            # Filter out any feeds that the user is already subscribed to
            existing_subscriptions = set(
                Subscription.objects.filter(q).values_list("feed__url", flat=True)
            )

            for feed in parsed.feeds:

                if feed.url in existing_subscriptions:
                    skipped.append(feed.url)
                    continue

                fetching.append(feed)

                # Right now we're potentially re-scraping all feeds in the import list
                # If we're doing this then we probably want to pass the etag through?
                feed_category = feed.categories[0][0]
                category = feed_category if feed_category != "" else None
                jobs.append(
                    tasks.create_subscription(feed.url, category, request.user.id)
                )

            # TODO figure out how to save the args (urls) here to each job,
            # along with the metadata of the request.user_id who started the
            # request
            task = group(jobs)()

            task.save()

            # Cache temporary job information to redis
            task_metadata = {
                "id": task.id,
                "user_id": request.user.id,
                "skipped": skipped,
                "children": [
                    {
                        "id": child.id,
                        "url": feed.url,
                        "category": feed.categories[0][0],
                    }
                    for (child, feed) in zip(task.children, fetching)
                ],
            }

            cache.set_many(
                {task.id: task_metadata, f"{request.user.id}-import": task.id},
                60 * 30,
            )

            return redirect("feeds:opml-import-detail", task_id=task.id)

    else:
        form = OPMLUploadForm()

    if is_running:
        form.fields["file"].disabled = True

    data = {
        "form": form,
        "is_running": is_running,
    }

    if is_running:
        data["task_id"] = running_job

    return render(request, "feeds/import_feeds.html", data)


def feed_search(request: HttpRequest):
    """Searches for existing feeds"""

    try:
        search_term = request.GET["q"]
    except KeyError:
        return HttpResponseBadRequest(
            f"Missing required search term {request.path}?q=term"
        )

    # If the search term is a URL we need to strip the scheme
    # I..e if 'http://site/index.xml' is entered instead of 'http://site/index.xml'
    # We want to match on just 'site/index.xml'

    is_url = parser.is_valid_url(search_term)

    # First attempt to lookup pre-existing/similar feeds
    feeds = (
        Feed.objects.prefetch_related("entries")
        .annotate(
            search=SearchVector("title", "url", "link"),
            subscribed=Exists(Subscription.objects.filter(feed=OuterRef("pk"))),
        )
        .filter(search=parser.strip_scheme(search_term) if is_url else search_term)
    )

    return JsonResponse(
        [
            {
                "title": feed.title,
                "subtitle": feed.subtitle,
                "subscribed": getattr(feed, "subscribed", None),
                "links": {
                    "internal": feed.get_absolute_url(),
                    "external": feed.link,
                    "rss": feed.url,
                },
                "entries": [
                    {"title": entry.title, "link": entry.get_absolute_url()}
                    for entry in feed.entries.all()[:3]
                ],
            }
            for feed in feeds
        ],
        safe=False,
    )


@login_required
def search(request: HttpRequest):
    search_term = request.GET.get("q")
    entries = Entry.objects.prefetch_related("feed__subscriptions").filter(
        title__search=search_term, feed__subscriptions__user=request.user
    )[:100]
    subscriptions = Subscription.objects.select_related("feed").filter(
        feed__title__search=search_term, user=request.user
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
                    resp = parser.crawl_url(search_term)
                    if resp is not None:
                        logger.info("Parsing resp: {}".format(search_term))
                        feed = parser.ingest_feed(resp, search_term)
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
            feeds = (
                Feed.objects.prefetch_related("entries")
                .annotate(
                    search=SearchVector("title", "url"),
                    subscribed=Exists(
                        Subscription.objects.filter(
                            feed=OuterRef("pk"), user=request.user
                        )
                    ),
                )
                .filter(
                    search=parser.strip_scheme(search_term) if is_url else search_term
                )
            )
            if feeds:
                logger.info("Found existing matches for: '{}'".format(search_term))

        return render(
            request,
            "feeds/discover.html",
            {
                "feeds": feeds,
            },
        )

    else:
        return render(
            request,
            "feeds/discover.html",
        )


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
