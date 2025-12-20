from django.shortcuts import render
from django.db.models import Count

from social.models import Contact, Group


def list_contacts(request):
    groups = Group.objects.all().annotate(member_count=Count("members"))

    # Get distinct relationship types from ContactRelationship model with counts
    relationship_types = (
        Contact.objects.values("relationship_to_me")
        .annotate(count=Count("relationship_to_me"))
        .order_by("count")
    )

    print(groups)
    print(relationship_types)
    return render(
        request,
        "social/contact_list.html",
        {
            "groups": groups,
            "relationship_types": relationship_types,
        },
    )
