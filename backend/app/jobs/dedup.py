from rapidfuzz import fuzz

from app.jobs.normalize import normalize_text
from app.schemas import JobPosting

FUZZY_TITLE = 90


def _key(text: str) -> str:
    """Normalised, space-free form: 'دیجی‌کالا' and 'دیجی کالا' compare equal."""
    return normalize_text(text).replace("\u200c", "").replace(" ", "")


def _better(a: JobPosting, b: JobPosting) -> JobPosting:
    """Prefer more requirements, then the newer published_at."""
    ka = (len(a.requirements), a.published_at or "")
    kb = (len(b.requirements), b.published_at or "")
    return b if kb > ka else a


def _is_dup(a: JobPosting, b: JobPosting) -> bool:
    if a.url == b.url:
        return True
    if _key(a.company) != _key(b.company) or _key(a.location) != _key(b.location):
        return False
    ta, tb = normalize_text(a.title), normalize_text(b.title)
    return _key(ta) == _key(tb) or fuzz.token_set_ratio(ta, tb) >= FUZZY_TITLE


def dedup(postings: list[JobPosting]) -> list[JobPosting]:
    """Remove duplicates across sources.

    Duplicate = same url, or same company + location with identical normalised title or a fuzzy
    title match (token-set ratio >= 90). Keeps the posting with the most requirements, then the
    newest published_at; the survivor stays at the first duplicate's position.
    """
    kept: list[JobPosting] = []
    for p in postings:
        for i, k in enumerate(kept):
            if _is_dup(k, p):
                kept[i] = _better(k, p)
                break
        else:
            kept.append(p)
    return kept
