from django.urls import path

from . import views

app_name = "feeds"
urlpatterns = [
    path("", views.index, name="index"),
    path("search", views.search, name="search"),
    path("feeds/", views.feed_list, name="feed-list"),
    path("feeds/search/", views.feed_search, name="feed-search"),
    path("feeds/import/opml", views.import_opml_feeds, name="opml-import"),
    path(
        "feeds/import/<str:task_id>",
        views.import_feed_detail,
        name="opml-import-detail",
    ),
    path("feeds/export/opml", views.export_opml_feeds, name="opml-export"),
    path("categories/", views.category_list, name="category-list"),
    path(
        "category/<slug:slug>", views.CategoryDetail.as_view(), name="category-detail"
    ),
    path(
        "category/delete/<int:pk>",
        views.CategoryDeleteView.as_view(),
        name="category-delete",
    ),
    path("accounts/profile/", views.profile, name="profile"),
    path(
        "subscriptions/delete/<int:pk>",
        views.SubscriptionDeleteView.as_view(),
        name="subscription-delete",
    ),
    path(
        "feed/discover/",
        views.discover,
        name="feed-discover",
    ),
    path(
        "feed/<slug:feed_slug>/",
        views.feed_detail,
        name="feed-detail",
    ),
    path(
        "feed/<slug:feed_slug>/follow",
        views.feed_follow,
        name="follow",
    ),
    path(
        "feed/<slug:feed_slug>/<str:uuid>/<slug:entry_slug>",
        views.entry_detail,
        name="entry-detail",
    ),
    path(
        "task/<str:task_id>",
        views.task_status,
        name="task-status",
    ),
    path(
        "task/group/<str:task_id>",
        views.task_group_status,
        name="task-group-status",
    ),
]
