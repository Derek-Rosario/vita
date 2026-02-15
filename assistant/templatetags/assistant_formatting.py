from django import template
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
    "a": ["href", "title", "rel"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
}

ALLOWED_PROTOCOLS = set(bleach.sanitizer.ALLOWED_PROTOCOLS).union({"mailto"})


def _render_assistant_markdown(text: str) -> str:
    rendered = markdown.markdown(
        text,
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
