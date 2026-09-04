"""Shared text normalization helpers for ingested feed content."""

from __future__ import annotations

import html
import re
from typing import Optional

_SCRIPT_RE = re.compile(r"(?is)<script[^>]*>.*?</script>")
_STYLE_RE = re.compile(r"(?is)<style[^>]*>.*?</style>")
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(text: Optional[str]) -> Optional[str]:
    """Reduce feed markup to plain readable prose.

    RSS payloads (Google News and The Guardian especially) wrap summaries in
    anchors and paragraphs. Those tags leak straight into the UI unless the text
    is normalized both on the way into the DB and on the way back out, so this
    is applied at ingestion and again at serialization.
    """
    if not text:
        return text
    cleaned = _SCRIPT_RE.sub(" ", text)
    cleaned = _STYLE_RE.sub(" ", cleaned)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = html.unescape(cleaned)
    # Entity decoding can reveal tags that arrived escaped (&lt;p&gt;), so sweep again.
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("\xa0", " ")
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def clean_feed_text(text: Optional[str]) -> Optional[str]:
    """Strip markup and collapse an all-whitespace result down to None."""
    return strip_html(text) or None
