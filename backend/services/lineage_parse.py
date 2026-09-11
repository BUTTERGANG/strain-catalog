"""Best-effort parent-strain extraction from free-text strain descriptions.

Used as a fallback on the strain detail page when we have no structured
lineage (no StrainLink rows, no `genetics` string) but the scraped
description spells the cross out in prose, e.g.

    "...comes from a cross between Dark Night and Blue Dream."

Deliberately conservative: only high-confidence "cross" phrasings. Real parent
names are Title Case and separated by lowercase connective words ("and", "the",
"popular"…), so scanning the clause for Title-Case runs segments them cleanly.
"""
import re

_STOPWORDS = {
    "the", "a", "an", "and", "of", "or", "with", "from", "this", "that", "these",
    "those", "its", "their", "his", "her", "our", "your", "it", "she", "he", "they",
    "strain", "strains", "hybrid", "indica", "sativa", "cross", "genetics", "cannabis",
    "bud", "buds", "plant", "plants", "phenotype", "cultivar", "variety", "seeds",
    "breeder", "breeders", "unknown", "mystery", "landrace", "sativas", "indicas",
    "legendary", "famous", "infamous", "classic", "potent", "popular", "rare",
    "flavor", "flavors", "effect", "effects", "aroma", "high", "two", "three", "both",
}

# A strain-name-shaped run: each word starts uppercase or a digit, with a few
# lowercase connector words allowed mid-name ("Jack the Ripper", "Wrath of God").
_NAME = (
    r"[A-Z0-9][A-Za-z0-9'’.\-#]*"
    r"(?:\s+(?:the|of|da|de|la|von|del|[A-Z0-9#][A-Za-z0-9'’.\-#]*)){0,4}"
)
_NAME_RE = re.compile(_NAME)

# "cross between / cross of / crossed from" — anchor; parents follow.
# No _NAME here, so IGNORECASE is safe.
_ANCHOR_RE = re.compile(r"\bcross(?:ed|ing)?\s+(?:between|of|from)\s+", re.IGNORECASE)
# "X crossed with Y" / "X x Y" — both parents named around the operator.
# NOT IGNORECASE: _NAME relies on a real uppercase/digit anchor, which
# re.IGNORECASE would defeat. Only the keyword needs case folding.
_PAIR_RE = re.compile(
    rf"(?P<a>{_NAME})\s+(?:(?i:crossed\s+with)|[xX]|×)\s+(?P<b>{_NAME})"
)
_PAREN_RE = re.compile(rf"\(\s*(?P<a>{_NAME})\s*(?:x|×|/)\s*(?P<b>{_NAME})\s*\)")

# Phrases that end the parent list within a sentence.
_CLAUSE_END_RE = re.compile(
    r"\.(?:\s|$)|\bto\s+(?:form|make|create|produce|yield|give)\b|\bresulting\b|"
    r"\bwhich\b|\bthat\b|\bwhere\b|\bbut\b|\bby\s+(?:unknown|mystery|the)\b",
    re.IGNORECASE,
)


def _clean(name: str) -> str:
    return re.sub(r"^[\s\-–—.,;:&/]+|[\s\-–—.,;:&/]+$", "", name or "").strip()


def _valid(name: str) -> bool:
    name = _clean(name)
    if not (3 <= len(name) <= 40):
        return False
    words = name.split()
    if not words or len(words) > 5:
        return False
    if not any(c.isalpha() for c in name):
        return False
    if name.lower() in _STOPWORDS:
        return False
    # Reject fragments that start or end on a filler word ("Dream of the",
    # "Two Phenos") — interior ones are fine ("Jack the Ripper").
    if words[0].lower() in _STOPWORDS or words[-1].lower() in _STOPWORDS:
        return False
    return name[0].isupper() or name[0].isdigit()


def _dedup(names, strain_name, out, seen):
    sn = strain_name.strip().lower()
    for cand in names:
        cand = _clean(cand)
        if not _valid(cand):
            continue
        key = cand.lower()
        if key == sn or key in seen:
            continue
        seen.add(key)
        out.append(cand)


def parse_parents(description: str, strain_name: str = "") -> list[str]:
    """Return an ordered, de-duplicated list of likely parent strain names.

    Empty list when nothing crosses the confidence bar.
    """
    if not description:
        return []

    out: list[str] = []
    seen: set[str] = set()

    # 1. "cross between <clause>" — scan the clause for Title-Case name runs.
    m = _ANCHOR_RE.search(description)
    if m:
        rest = description[m.end():]
        end = _CLAUSE_END_RE.search(rest)
        clause = rest[: end.start()] if end else rest[:140]
        _dedup(_NAME_RE.findall(clause), strain_name, out, seen)

    # 2. "X crossed with Y" / "X x Y" / "(X x Y)".
    for rx in (_PAIR_RE, _PAREN_RE):
        pm = rx.search(description)
        if pm:
            _dedup([pm.group("a"), pm.group("b")], strain_name, out, seen)

    # A lone parent is usually a false positive ("cross between two phenos of X").
    return out[:4] if len(out) >= 2 else []


def genetics_string(parents: list[str]) -> str:
    """Render parents as a display string, e.g. 'Dark Night × Blue Dream'."""
    return " × ".join(parents)
