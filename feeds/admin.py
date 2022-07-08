from django.contrib import admin
from django.db.models.aggregates import Count

from .models import Category, Entry, Feed, Subscription


@admin.register(Feed)
class FeedAdmin(admin.ModelAdmin):
    list_display = ("title", "url", "etag", "last_modified", "subscribers")
    fields = (
        "url",
        "title",
        "slug",
        "link",
        "etag",
        "last_modified",
        "subscribers",
        "last_checked",
    )
    readonly_fields = (
        "title",
        "link",
        "slug",
        "etag",
        "last_modified",
        "subscribers",
        "last_checked",
    )
    search_fields = ["title", "url", "link", "slug"]

    def get_queryset(self, request):
        queryset = super(FeedAdmin, self).get_queryset(request)
        return queryset.annotate(subscribers=Count("subscriptions"))

    def subscribers(self, obj):
        return obj.subscribers


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    pass


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ("title", "link", "guid", "feed", "published", "updated")
    search_fields = ["feed__title"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "feed", "category")
