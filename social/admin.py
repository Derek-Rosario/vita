from django.contrib import admin

from social.models import (
    Contact,
    ContactRelationship,
    ContactTouchpoint,
    Interest,
    Group,
)


class ContactTouchpointInline(admin.TabularInline):
    model = ContactTouchpoint
    extra = 0
    fields = ("date", "channel", "sentiment", "notes")
    readonly_fields = ()
    ordering = ("-date",)


class GroupInline(admin.TabularInline):
    model = Group.members.through
    extra = 0


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = (
        "first_name",
        "last_name",
        "relationship_to_me",
        "priority",
        "check_in_frequency_days",
        "last_contacted_at",
    )
    list_filter = ("relationship_to_me", "priority", "preferred_channel")
    search_fields = ("first_name", "last_name", "notes")
    prepopulated_fields = {"slug": ("first_name", "last_name")}
    inlines = [ContactTouchpointInline, GroupInline]


@admin.register(ContactTouchpoint)
class ContactTouchpointAdmin(admin.ModelAdmin):
    list_display = ("contact", "date", "channel", "sentiment")
    list_filter = ("channel", "sentiment")
    date_hierarchy = "date"
    search_fields = ("contact__first_name", "contact__last_name", "notes")
    autocomplete_fields = ("contact",)


@admin.register(ContactRelationship)
class ContactRelationshipAdmin(admin.ModelAdmin):
    list_display = ("from_contact", "to_contact", "relationship_type", "updated_at")
    list_filter = ("relationship_type",)
    search_fields = ("from_contact__name", "to_contact__name")
    autocomplete_fields = ("from_contact", "to_contact")


@admin.register(Interest)
class InterestAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("members",)
    autocomplete_fields = ("members",)
