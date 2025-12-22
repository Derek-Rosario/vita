from django import forms
from django.utils import timezone

from social.models import Contact, ContactTouchpoint


class QuickAddContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ["first_name", "last_name", "relationship_to_me", "preferred_channel"]


class ContactTouchpointForm(forms.ModelForm):
    class Meta:
        model = ContactTouchpoint
        fields = ["contact", "date", "channel", "sentiment", "notes"]
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
        self.fields["channel"].widget.attrs["class"] = "form-select"
        self.fields["sentiment"].widget.attrs["class"] = "form-select"
        self.fields["contact"].widget.attrs["class"] = "form-select"

        if contact is not None:
            self.fields["contact"].initial = contact
            self.fields["contact"].widget = forms.HiddenInput()
