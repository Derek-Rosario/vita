from django.shortcuts import render
from django.db.models import Count
from django.views.decorators.http import require_POST

from core.services import add_toast, add_htmx_trigger
from core.views import HttpRequest
from social.forms import QuickAddContactForm
from social.models import Contact, Group


def index(request: HttpRequest):
    groups = Group.objects.all().annotate(member_count=Count("members"))

    # Get distinct relationship types from ContactRelationship model with counts
    relationship_types = (
        Contact.objects.values("relationship_to_me")
        .annotate(count=Count("relationship_to_me"))
        .order_by("count")
    )

    template_name = "social/index.html"

    if request.htmx:
        template_name += "#contacts"

    return render(
        request,
        template_name,
        {
            "groups": groups,
            "relationship_types": relationship_types,
            "quick_add_contact_form": QuickAddContactForm(),
        },
    )


@require_POST
def quick_add_contact(request: HttpRequest):
    form = QuickAddContactForm(request.POST)
    if form.is_valid():
        form.save()
        response = render(
            request,
            "social/partials/quick_add_contact_form.html",
            {"form": QuickAddContactForm()},
        )
        add_htmx_trigger(response, "contactListChanged")
        add_toast(response, "success", "Contact added successfully.")
        return response
    return render(
        request,
        "social/partials/quick_add_contact_form.html",
        {"form": form},
        status=400,
    )
