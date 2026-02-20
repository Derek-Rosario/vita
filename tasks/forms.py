from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from tasks.models import Comment, Project, Routine, RoutineStep, Tag, Task, TaskStatus


def _coerce_to_aware_datetime(value):
    if value is None:
        return None
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _current_datetime_local_input_max() -> str:
    return (
        timezone.localtime().replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    )


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = [
            "title",
            "description",
            "status",
            "completed_at",
            "project",
            "priority",
            "energy",
            "due_at",
            "estimate_minutes",
            "parent",
            "tags",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Details"}
            ),
            "completed_at": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"},
                format="%Y-%m-%dT%H:%M",
            ),
            "due_at": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "estimate_minutes": forms.NumberInput(attrs={"class": "form-control"}),
            "status": forms.RadioSelect(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["completed_at"].required = False
        self.fields["completed_at"].input_formats = [
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
        ]
        self.fields[
            "completed_at"
        ].help_text = "Adjust this if you completed the task earlier or later than it was marked done."
        if self.instance.status != TaskStatus.DONE:
            self.fields.pop("completed_at")
        else:
            self.fields["completed_at"].widget.attrs["max"] = (
                _current_datetime_local_input_max()
            )

        self.fields["parent"].queryset = Task.objects.filter(
            status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS]
        ).order_by("-created_at")
        for name in ["priority", "energy", "parent", "tags"]:
            widget = self.fields[name].widget
            css = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{css} form-select".strip()

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("status") != TaskStatus.DONE:
            return cleaned_data

        completed_at = _coerce_to_aware_datetime(cleaned_data.get("completed_at"))
        if completed_at is None:
            return cleaned_data

        cleaned_data["completed_at"] = completed_at
        if completed_at > timezone.now():
            self.add_error(
                "completed_at",
                "Completion date/time cannot be in the future.",
            )

        return cleaned_data


class TaskCompletionTimeForm(forms.Form):
    completed_at = forms.DateTimeField(
        label="Completion date and time",
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"],
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"},
            format="%Y-%m-%dT%H:%M",
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["completed_at"].widget.attrs["max"] = (
            _current_datetime_local_input_max()
        )

    def clean_completed_at(self):
        completed_at = _coerce_to_aware_datetime(self.cleaned_data["completed_at"])
        if completed_at > timezone.now():
            raise forms.ValidationError("Completion date/time cannot be in the future.")
        return completed_at


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["content"]
        widgets = {
            "content": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "Add a comment...",
                },
            )
        }


DAY_OF_WEEK_CHOICES = [
    (0, "Sunday"),
    (1, "Monday"),
    (2, "Tuesday"),
    (3, "Wednesday"),
    (4, "Thursday"),
    (5, "Friday"),
    (6, "Saturday"),
]


class RoutineForm(forms.ModelForm):
    days_of_week = forms.TypedMultipleChoiceField(
        required=False,
        coerce=int,
        choices=DAY_OF_WEEK_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select days for weekly cadence (optional).",
    )

    class Meta:
        model = Routine
        fields = [
            "name",
            "description",
            "tags",
            "is_active",
            "interval",
            "days_of_week",
            "day_of_month",
            "anchor_time",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Describe the routine",
                }
            ),
            "day_of_month": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 31}
            ),
            "interval": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "anchor_time": forms.TimeInput(
                attrs={"class": "form-control", "type": "time"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        widget = self.fields["tags"].widget
        css = widget.attrs.get("class", "")
        widget.attrs["class"] = f"{css} form-select".strip()
        if self.instance and self.instance.pk and self.instance.days_of_week:
            self.initial["days_of_week"] = self.instance.days_of_week

    def clean_days_of_week(self):
        days = self.cleaned_data.get("days_of_week") or []
        return sorted(set(days))


class RoutineStepForm(forms.ModelForm):
    class Meta:
        model = RoutineStep
        fields = [
            "title",
            "description",
            "sort_order",
            "default_priority",
            "default_energy",
            "default_estimate_minutes",
            "default_tags",
            "is_stackable",
            "is_available_away_from_home",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "What happens in this step?",
                }
            ),
            "sort_order": forms.NumberInput(attrs={"class": "form-control"}),
            "default_estimate_minutes": forms.NumberInput(
                attrs={"class": "form-control"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["default_priority", "default_energy", "default_tags"]:
            widget = self.fields[name].widget
            css = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{css} form-select".strip()


RoutineStepFormSet = inlineformset_factory(
    Routine,
    RoutineStep,
    form=RoutineStepForm,
    extra=2,
    can_delete=True,
)


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "is_active", "tags"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "What is this project about?",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        widget = self.fields["tags"].widget
        css = widget.attrs.get("class", "")
        widget.attrs["class"] = f"{css} form-select".strip()


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ["name", "color", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "color": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "#RRGGBB (optional)"}
            ),
        }
