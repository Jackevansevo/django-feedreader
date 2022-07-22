import listparser
from celery.result import AsyncResult
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count
from django.db.utils import IntegrityError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic.detail import DetailView
from django.views.generic.edit import CreateView, DeleteView

import feeds.tasks as tasks

from .forms import CategoryForm, OPMLUploadForm, SignUpForm, SubscriptionCreateForm
from .models import Category, Entry, Feed, Subscription

# TODO Mechanism to all the subtasks status from a parent tasks
# Or task status for multiple tasks


def task_status(_: HttpRequest, task_id) -> JsonResponse:
    task_result = AsyncResult(task_id)
    result = {
        "id": task_id,
        "status": task_result.status,
        "result": task_result.result,
    }
    return JsonResponse(result)


def import_opml_feeds(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = OPMLUploadForm(request.POST, request.FILES)
        if form.is_valid():
            f = request.FILES["file"]
            contents = f.read()
            parsed = listparser.parse(contents)

            async_tasks = []
            for feed in parsed.feeds:
                feed_category = feed.categories[0][0]
                category = feed_category if feed_category != "" else None
                task = tasks.add_subscription.delay(feed.url, category, request.user.id)
                async_tasks.append({"id": task.id, "url": feed.url})

            return JsonResponse({"tasks": async_tasks})
    else:
        form = OPMLUploadForm()

    return render(request, "feeds/import_feeds.html", {"form": form})


def export_opml_feeds(request: HttpRequest) -> HttpResponse:
    subscriptions = (
        Subscription.objects.values(
            "feed__url", "feed__link", "category__name", "feed__title", "feed__subtitle"
        )
        .filter(user=request.user)
        .order_by("category__name")
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


class ProfileView(DetailView):
    template_name = "profile.html"
    model = User

    def get_object(self, queryset=None):
        return self.request.user


class CategoryDetail(DetailView):
    model = Category

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user)


class CategoryDeleteView(DeleteView):
    model = Category
    success_url = reverse_lazy("feeds:category-list")

    def get_queryset(self):
        return Category.objects.filter(user=self.request.user)

    def form_valid(self, form):
        messages.warning(self.request, f"Deleted: '{self.object}'")
        return super().form_valid(form)


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


def index(request: HttpRequest) -> HttpResponse:
    entries = Entry.objects.select_related("feed").filter(
        feed__subscriptions__user=request.user, published__lte=timezone.now()
    )
    paginator = Paginator(entries, 50)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    return render(request, "feeds/index.html", {"page_obj": page_obj})


def feed_list(request: HttpRequest) -> HttpResponse:
    subscriptions = (
        Subscription.objects.select_related("feed", "user", "category")
        .filter(user=request.user)
        .order_by("feed__title")
    )
    return render(request, "feeds/feed_list.html", {"subscriptions": subscriptions})


def feed_detail(request: HttpRequest, feed_slug: str) -> HttpResponse:
    subscription = get_object_or_404(
        Subscription, feed__slug=feed_slug, user=request.user
    )
    return render(
        request,
        "feeds/feed_detail.html",
        {
            "subscription": subscription,
            "subscription": subscription,
            "feed": subscription.feed,
        },
    )


def entry_detail(request: HttpRequest, feed_slug: str, entry_slug: str) -> HttpResponse:
    entry = get_object_or_404(
        Entry,
        feed__subscriptions__user=request.user,
        slug=entry_slug,
        feed__slug=feed_slug,
    )
    return render(request, "feeds/entry_detail.html", {"entry": entry})


def feed_create_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        # create a form instance and populate it with data from the request:
        form = SubscriptionCreateForm(request.POST, user=request.user)
        # check whether it's valid:
        if form.is_valid():
            url = Feed.find_feed_from_url(form.cleaned_data["url"])
            # Check if the feed exists
            try:
                Subscription.objects.get(feed__url=url, user=request.user)
            except Subscription.DoesNotExist:
                # Go and create the feed
                category = form.cleaned_data["category"]
                task = tasks.add_subscription.delay(
                    url, getattr(category, "name", None), request.user.id
                )
                return JsonResponse({"id": task.id})
            else:
                form.add_error("url", "Already subscribed to this feed")
                return render(request, "feeds/subscription_form.html", {"form": form})

    form = SubscriptionCreateForm(user=request.user)
    return render(request, "feeds/subscription_form.html", {"form": form})


class SubscriptionDeleteView(DeleteView):
    model = Subscription
    success_url = reverse_lazy("feeds:feed-list")

    def get_queryset(self):
        return Subscription.objects.filter(user=self.request.user)

    def form_valid(self, form):
        messages.warning(self.request, f"Unsubscribed from: '{self.object.feed}'")
        return super().form_valid(form)
