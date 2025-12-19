from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse

from vita import settings


class SuperuserRequiredMiddleware:
    """
    Require authentication (and superuser) for all requests except a small allowlist.
    Intended for single-user setups.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_paths = {
            reverse("login"),
            reverse("logout"),
        }

    def __call__(self, request):
        path: str = request.path

        if (
            path.startswith("/static/")
            or path.startswith("/__reload__/")
            or path.startswith("/favicon.ico")
            or path.startswith("/admin/login")
            or path.startswith("/admin/js")
        ):
            return self.get_response(request)

        if path.startswith("/api/"):
            # Check API key
            print(request.headers)
            if request.headers.get("X-Vita-Api-Key") != settings.VITA_API_KEY:
                return HttpResponseForbidden("Missing or invalid API key.")
            return self.get_response(request)

        if path in self.exempt_paths:
            return self.get_response(request)

        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={path}")

        if not request.user.is_superuser:
            return HttpResponseForbidden("Superuser required.")

        return self.get_response(request)
