from celery import chain, group
from django.contrib import admin
from django.db.models.aggregates import Count
from django.http import HttpResponseRedirect
from django.urls import path

from feeds.tasks import fetch_feed, refresh_feeds, update_feed

from .models import Category, Entry, Feed, Subscription


@admin.register(Feed)
class FeedAdmin(admin.ModelAdmin):
    change_form_template = "feeds/feed_changeform.html"
    change_list_template = "feeds/feeds_changelist.html"

    list_display = ("title", "url", "etag", "last_modified", "subscribers")
    fields = (
        "url",
        "title",
        "subtitle",
        "slug",
        "link",
        "etag",
        "last_modified",
        "subscribers",
        "last_checked",
    )
    readonly_fields = (
        "title",
        "subtitle",
        "link",
        "slug",
        "etag",
        "last_modified",
        "subscribers",
        "last_checked",
    )
    search_fields = ["title", "url", "link", "slug"]
    actions = ["refresh"]

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path("refresh/", self.refresh_all),
        ]
        return my_urls + urls

    def refresh_all(self, request):
        res = refresh_feeds()
        self.message_user(request, f"Triggered post refresh {res.id}")
        return HttpResponseRedirect("../")

    def get_queryset(self, request):
        queryset = super(FeedAdmin, self).get_queryset(request)
        return queryset.annotate(subscribers=Count("subscriptions"))

    def subscribers(self, obj):
        return obj.subscribers

    def save_model(self, request, feed, form, change):
        if "_refresh" in request.POST:
            res = chain(
                fetch_feed.s(feed.url, feed.last_modified, feed.etag),
                update_feed.s(feed.id, feed.url),
            )()
            resp = res.get()
            self.message_user(request, f"Refreshed feed {feed.url} resp: {resp}")
        super().save_model(request, feed, form, change)

    @admin.action(description="Refresh selected feeds")
    def refresh(self, request, queryset):
        feeds = (
            queryset.annotate(subscribers=Count("subscriptions"))
            .filter(subscribers__gt=0)
            .values("id", "url", "last_modified", "etag")
        )
        group(
            chain(
                fetch_feed.s(f["url"], f["last_modified"], f["etag"]),
                update_feed.s(f["id"], f["url"]),
            )
            for f in feeds
        ).apply_async()


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    pass


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ("title", "link", "guid", "feed", "published", "updated")
    search_fields = ["feed__title", "title"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("feed", "user", "category")
    search_fields = ["feed__title", "user__username", "user__email"]
