import html
import re
from urllib.parse import quote_plus

from django import template
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe
import bleach
import markdown

register = template.Library()

ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS).union(
    {
        "p",
        "br",
        "pre",
        "code",
        "blockquote",
        "ul",
        "ol",
        "li",
        "strong",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "time",
        "button",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)

ALLOWED_ATTRIBUTES = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "a": ["href", "title", "rel", "class"],
    "time": ["datetime", "title", "class"],
    "button": ["type", "class", "data-assistant-followup", "data-followup-reply"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
}

ALLOWED_PROTOCOLS = set(bleach.sanitizer.ALLOWED_PROTOCOLS).union({"mailto"})

ENTITY_URL_TEMPLATES = {
    "task": "/tasks/task/{entity_id}/edit/",
    "routine": "/tasks/routines/{entity_id}/",
    "routine_step": "/tasks/routines/steps/{entity_id}/",
    "project": "/tasks/projects/{entity_id}/",
    "tag": "/tasks/tags/{entity_id}/",
}

ENTITY_TOKEN_PATTERN = re.compile(
    r"\[\[(?P<kind>task|routine|routine_step|project|tag):(?P<id>\d+)(?:\|(?P<label>[^\]]+))?\]\]"
)
CONTACT_TOKEN_PATTERN = re.compile(r"\[\[contact:(?P<label>[^\]]+)\]\]")
TIMESTAMP_TOKEN_PATTERN = re.compile(
    r"\[\[ts:(?P<value>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]"
)
FOLLOWUP_TOKEN_PATTERN = re.compile(
    r"\[\[suggest:(?P<label>[^\]|]+)(?:\|(?P<reply>[^\]]+))?\]\]"
)


def _replace_entity_token(match: re.Match[str]) -> str:
    kind = match.group("kind")
    entity_id = match.group("id")
    label = (match.group("label") or f"{kind.replace('_', ' ').title()} #{entity_id}").strip()
    href = ENTITY_URL_TEMPLATES[kind].format(entity_id=entity_id)
    safe_label = html.escape(label)
    safe_kind = kind.replace("_", "-")
    return (
        f'<a class="assistant-entity-link assistant-entity-link-{safe_kind}" '
        f'href="{href}">{safe_label}</a>'
    )


def _replace_contact_token(match: re.Match[str]) -> str:
    label = match.group("label").strip()
    if not label:
        return match.group(0)
    safe_label = html.escape(label)
    href = f"/social/contacts?search={quote_plus(label)}"
    return (
        '<a class="assistant-entity-link assistant-entity-link-contact" '
        f'href="{href}">{safe_label}</a>'
    )


def _format_human_datetime(value) -> str:
    local_value = timezone.localtime(value)
    date_part = local_value.strftime("%a, %b %d, %Y")
    time_part = local_value.strftime("%I:%M %p").lstrip("0")
    tz_part = local_value.strftime("%Z").strip()
    if tz_part:
        return f"{date_part} at {time_part} {tz_part}"
    return f"{date_part} at {time_part}"


def _replace_timestamp_token(match: re.Match[str]) -> str:
    raw_value = match.group("value").strip()
    display_override = (match.group("label") or "").strip()

    parsed_datetime = parse_datetime(raw_value)
    if parsed_datetime is not None:
        if timezone.is_naive(parsed_datetime):
            parsed_datetime = timezone.make_aware(
                parsed_datetime,
                timezone.get_current_timezone(),
            )
        local_value = timezone.localtime(parsed_datetime)
        display_value = display_override or _format_human_datetime(local_value)
        safe_display = html.escape(display_value)
        safe_title = html.escape(local_value.isoformat())
        safe_datetime = html.escape(local_value.isoformat())
        return (
            '<time class="assistant-timestamp" '
            f'datetime="{safe_datetime}" title="{safe_title}">{safe_display}</time>'
        )

    parsed_date = parse_date(raw_value)
    if parsed_date is not None:
        display_value = display_override or parsed_date.strftime("%a, %b %d, %Y")
        safe_display = html.escape(display_value)
        safe_title = html.escape(parsed_date.isoformat())
        safe_datetime = html.escape(parsed_date.isoformat())
        return (
            '<time class="assistant-timestamp" '
            f'datetime="{safe_datetime}" title="{safe_title}">{safe_display}</time>'
        )

    return match.group(0)


def _replace_followup_token(match: re.Match[str]) -> str:
    label = match.group("label").strip()
    reply = (match.group("reply") or label).strip()

    if not label or not reply:
        return match.group(0)

    safe_label = html.escape(label)
    safe_reply = html.escape(reply, quote=True)
    return (
        '<button type="button" '
        'class="assistant-followup-chip" '
        'data-assistant-followup="1" '
        f'data-followup-reply="{safe_reply}">{safe_label}</button>'
    )


def _inject_entity_links(text: str) -> str:
    with_entities = ENTITY_TOKEN_PATTERN.sub(_replace_entity_token, text)
    with_contacts = CONTACT_TOKEN_PATTERN.sub(_replace_contact_token, with_entities)
    with_timestamps = TIMESTAMP_TOKEN_PATTERN.sub(_replace_timestamp_token, with_contacts)
    return FOLLOWUP_TOKEN_PATTERN.sub(_replace_followup_token, with_timestamps)


def _render_assistant_markdown(text: str) -> str:
    linked_text = _inject_entity_links(text)
    rendered = markdown.markdown(
        linked_text,
        extensions=[
            "fenced_code",
            "tables",
            "sane_lists",
            "nl2br",
        ],
    )
    sanitized = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    return bleach.linkify(sanitized)


@register.filter(name="render_chat_message")
def render_chat_message(content: str, role: str = "assistant"):
    text = "" if content is None else str(content)
    if role == "assistant":
        return mark_safe(_render_assistant_markdown(text))

    escaped = conditional_escape(text).replace("\n", "<br>")
    return mark_safe(escaped)
