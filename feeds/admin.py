from django.contrib import admin
from django.db.models.aggregates import Count


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
        "favicon",
        "etag",
        "last_modified",
        "subscribers",
        "last_checked",
    )
    readonly_fields = (
        "title",
        "subtitle",
        "link",
        "favicon",
        "slug",
        "etag",
        "last_modified",
        "subscribers",
        "last_checked",
    )
    search_fields = ["title", "url", "link", "slug"]
    actions = ["refresh"]

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
    search_fields = ["feed__title", "title"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("feed", "user", "category")
    search_fields = ["feed__title", "user__username", "user__email"]
