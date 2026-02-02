from django.http import HttpRequest as HttpRequestBase
from django_htmx.middleware import HtmxDetails
from core.models import LastGeolocation
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from core.services import is_close_to_home


class HttpRequest(HttpRequestBase):
    htmx: HtmxDetails


@require_POST
def update_last_geolocation(request: HttpRequest):
    latitude = request.POST.get("latitude")
    longitude = request.POST.get("longitude")
    if latitude is None or longitude is None:
        return HttpResponse("Missing latitude or longitude", status=400)

    LastGeolocation.objects.update_or_create(
        pk=1,
        defaults={
            "latitude": latitude,
            "longitude": longitude,
        },
    )

    return HttpResponse(status=204)
