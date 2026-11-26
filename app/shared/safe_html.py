"""app.shared.safe_html — allowlisted inline markup for admin-editable copy (SEC-015).

Admin texts (landing headline, eyebrow, …) may carry a little emphasis markup
(the flagship headline uses ``<em>agentische</em>``), but must never inject
arbitrary HTML into public pages. ``inline_html`` escapes *everything* and then
re-enables exactly the bare tags ``<em>``, ``<strong>`` and ``<br>`` — no
attributes, so no event handlers / URLs can survive. The client-side language
switch (static/quiz/lang.js ``renderInline``) applies the identical allowlist.
"""

from __future__ import annotations

import re

from markupsafe import Markup, escape

ALLOWED_INLINE_TAGS = ("em", "strong", "br")

# Matches the *escaped* form of a bare allowlisted tag: &lt;em&gt;, &lt;/strong&gt;,
# &lt;br&gt;, &lt;br/&gt;, &lt;br /&gt; (case-insensitive, no attributes).
_ESCAPED_TAG_RE = re.compile(r"&lt;(/?)(em|strong|br)\s*/?&gt;", re.IGNORECASE)


def _restore(m: re.Match[str]) -> str:
    closing, tag = m.group(1), m.group(2).lower()
    if tag == "br":
        return "" if closing else "<br>"
    return f"<{closing}{tag}>"


def inline_html(text: object) -> Markup:
    """Escape ``text`` except for bare ``<em>``, ``<strong>``, ``<br>`` tags.

    Unbalanced tags are harmless (the browser auto-closes them at the end of
    the containing element). Registered as the Jinja filter ``inline_html``.
    """
    if text is None:
        return Markup("")
    return Markup(_ESCAPED_TAG_RE.sub(_restore, str(escape(text))))
