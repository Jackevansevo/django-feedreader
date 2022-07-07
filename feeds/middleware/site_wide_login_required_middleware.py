from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class SiteWideLoginRequiredMiddleware:
    def __init__(self, get_response):
        self.login_exempt = (
            settings.LOGIN_URL,
            reverse("sign_up"),
            reverse("password_reset"),
            reverse("feeds:feed-import"),
        )
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and request.path not in self.login_exempt:
            return redirect(settings.LOGIN_URL)

        response = self.get_response(request)

        return response
