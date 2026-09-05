"""HTML escaping helpers for user-generated content.

Every piece of user-supplied text MUST pass through esc() before being
embedded in an f-string template. Database content from trusted sources
(scrapes) may skip it, but user input never does.
"""
import html as _html


def esc(value) -> str:
    """Escape user content for safe HTML embedding (including attribute context)."""
    if value is None:
        return ""
    return _html.escape(str(value), quote=True)