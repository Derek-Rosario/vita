import re
from django import forms
from django.utils import timezone

from social.models import Contact, ContactTouchpoint, RelationshipType


class QuickAddContactForm(forms.ModelForm):
    name = forms.CharField(
        max_length=200, label="Full Name", help_text="First Last (nickname)"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default relationship type
        self.fields["relationship_to_me"].initial = RelationshipType.FRIEND

    class Meta:
        model = Contact
        fields = [
            "name",
            "relationship_to_me",
            "check_in_frequency_days",
            "priority",
            "preferred_channel",
        ]

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise forms.ValidationError("Name cannot be empty.")
        return name

    def save(self, commit=True):
        instance = super().save(commit=False)
        name = self.cleaned_data["name"]

        # Parse format: "First Last (Nickname)" or "First Last"
        match = re.match(r"^([^\(]+?)(?:\s+\(([^)]+)\))?$", name)

        if match:
            full_name = match.group(1).strip()
            nickname = match.group(2).strip() if match.group(2) else ""

            # Split by spaces; last part is last name, rest is first name
            parts = full_name.split()
            if len(parts) == 1:
                instance.first_name = parts[0]
                instance.last_name = ""
            else:
                instance.first_name = " ".join(parts[:-1])
                instance.last_name = parts[-1]

            instance.nickname = nickname

        if commit:
            instance.save()
        return instance


class ContactTouchpointForm(forms.ModelForm):
    contacts = forms.ModelMultipleChoiceField(
        queryset=Contact.objects.all(),
        widget=forms.SelectMultiple,
        required=True,
    )

    class Meta:
        model = ContactTouchpoint
        fields = ["date", "channel", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "What did you talk about?",
                }
            ),
        }

    def __init__(self, *args, contact=None, **kwargs):
        initial = kwargs.setdefault("initial", {})
        initial.setdefault("date", timezone.localdate())
        super().__init__(*args, **kwargs)

        if contact is not None:
            self.fields["contacts"].initial = [contact]
            self.fields["contacts"].widget = forms.HiddenInput()

    def save(self, commit=True):
        contacts = self.cleaned_data.pop("contacts")
        instances = []
        for contact in contacts:
            instance = super().save(commit=False)
            instance.pk = None
            instance._state.adding = True
            instance.contact = contact
            if commit:
                instance.save()
            instances.append(instance)
        return instances
