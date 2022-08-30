from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = (
    [
        path("", include("feeds.urls")),
        path("admin/", admin.site.urls),
        path("accounts/", include("allauth.urls")),
        path(
            "sw.js",
            TemplateView.as_view(template_name="sw.js", content_type="text/javascript"),
        ),
    ]
    + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
)

if settings.DEBUG:
    urlpatterns.append(path("__debug__/", include("debug_toolbar.urls")))
