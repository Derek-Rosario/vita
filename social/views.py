from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.db.models import Count
from django.views.decorators.http import require_POST
from django.db.models.functions import Lower

from core.services import add_toast, add_htmx_trigger
from core.views import HttpRequest
from social.forms import ContactTouchpointForm, QuickAddContactForm
from social.models import (
    Contact,
    ContactTouchpointSentiment,
    Group,
    RelationshipType,
)


def index(request: HttpRequest):
    groups = Group.objects.all().annotate(member_count=Count("members"))

    # Get distinct relationship types from ContactRelationship model with counts
    relationship_types = (
        Contact.objects.values("relationship_to_me")
        .annotate(count=Count("relationship_to_me"))
        .order_by("count")
    )

    contacts_needing_attention = Contact.objects.filter(strength__lt=70).order_by(
        "strength", Lower("first_name"), Lower("last_name")
    )

    template_name = "social/index.html"

    if request.htmx:
        template_name += "#contacts"

    return render(
        request,
        template_name,
        {
            "contacts_needing_attention": contacts_needing_attention,
            "groups": groups,
            "relationship_types": relationship_types,
            "quick_add_contact_form": QuickAddContactForm(),
        },
    )


def _contacts_needing_attention_card(request: HttpRequest):
    contacts_needing_attention = Contact.objects.filter(strength__lt=70).order_by(
        "strength", Lower("first_name"), Lower("last_name")
    )
    return render(
        request,
        "social/partials/contacts_needing_attention_card.html",
        {"contacts_needing_attention": contacts_needing_attention},
    )


def list_contacts(request: HttpRequest):
    # Apply search filter if provided
    search = request.GET.get("search", "").strip()
    if search:
        contacts = (
            Contact.objects.filter(first_name__icontains=search)
            | Contact.objects.filter(last_name__icontains=search)
            | Contact.objects.filter(nickname__icontains=search)
            | Contact.objects.filter(
                first_name__icontains=search.split(" ")[0],
                last_name__icontains=" ".join(search.split(" ")[1:]),
            )
        )
        contacts = contacts.order_by(Lower("first_name"), Lower("last_name"))
    else:
        contacts = Contact.objects.all().order_by(
            Lower("first_name"), Lower("last_name")
        )

    group_id = request.GET.get("group")
    if group_id:
        contacts = contacts.filter(groups__pk=group_id)

    relationship_to_me = request.GET.get("relationship_to_me")
    if relationship_to_me:
        contacts = contacts.filter(relationship_to_me=relationship_to_me)

    groups = Group.objects.all()
    relationship_types = RelationshipType.choices

    template_name = "social/contacts.html"

    if request.htmx:
        template_name += "#contacts"

    return render(
        request,
        template_name,
        {
            "search": search,
            "contacts": contacts,
            "groups": groups,
            "relationship_types": relationship_types,
            "selected_group": group_id,
            "selected_relationship": relationship_to_me,
        },
    )


def log_contact_touchpoint_modal(request: HttpRequest, contact_pk: str):
    contact = Contact.objects.get(pk=contact_pk)
    if request.method == "POST":
        form = ContactTouchpointForm(request.POST)
        if form.is_valid():
            form.save()
            response = HttpResponse(status=204)
            add_htmx_trigger(response, "contactTouchpointLogged")
            add_toast(response, "success", "Contact touchpoint logged successfully.")
            return response

    form = ContactTouchpointForm(
        initial={
            "contact": contact,
            "channel": contact.preferred_channel,
            "sentiment": ContactTouchpointSentiment.POSITIVE,
        }
    )
    return render(
        request,
        "social/partials/log_contact_touchpoint_modal.html",
        {"contact": contact, "form": form},
    )


@require_POST
def create_contact_task(request: HttpRequest, contact_pk: str) -> HttpResponse:
    contact = get_object_or_404(Contact, pk=contact_pk)
    created_task = contact.create_contact_task()
    response = HttpResponse(status=204)

    if created_task:
        add_htmx_trigger(response, "contactTaskCreated")
        add_toast(response, "success", "Contact task created successfully.")
    else:
        add_toast(
            response,
            "info",
            "A non-completed task for this contact already exists.",
        )
    return response


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
