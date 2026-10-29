"""Display cleanup, conservative exact skills, and sentence skills for job postings."""
import html
import re
import unicodedata
from functools import lru_cache

from app.careers import taxonomy as taxonomy_module
from app.careers.taxonomy import Taxonomy


def normalize_text(text: str) -> str:
    # Hazm-compatible character/spacing cleanup without changing technical punctuation.
    text = unicodedata.normalize("NFKC", html.unescape(text)).translate(str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی", "ة": "ه", "ۀ": "ه"}))
    text = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    text = text.replace("\u200f", "").replace("\u200e", "").replace("\ufeff", "")
    text = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text)
    return " ".join(text.split()).casefold()


def _key(text: str) -> str:
    cleaned = normalize_text(text).replace("\u200c", " ")
    helper = getattr(taxonomy_module, "normalize_text", None)
    # P1's matching convention is authoritative when integrated.
    # Keep punctuation significant for technical names and approved IDs.
    if re.search(r"[+#._]", cleaned):
        return " ".join(cleaned.split())
    return helper(cleaned) if helper else " ".join(cleaned.split())


def map_skills(skills: list[str], taxonomy: Taxonomy) -> list[str]:
    index: dict[str, set[str]] = {}
    for cid, concept in taxonomy.concepts.items():
        for label in [cid, concept.label_fa, concept.label_en, *concept.aliases]:
            index.setdefault(_key(label), set()).add(cid)
    approved = []
    for skill in skills:
        candidates = index.get(_key(skill), set())
        if len(candidates) == 1:
            cid = next(iter(candidates))
            if cid not in approved:
                approved.append(cid)
    return approved


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def clean_text(text: str) -> str:
    """Display-safe cleanup for stored fields: keeps ZWNJ and case (unlike `normalize_text`, which is
    for matching/keys). HTML entities, Arabic ي/ك -> ی/ک, digits -> ASCII, whitespace."""
    s = html.unescape(text or "").translate(_DIGITS)
    s = s.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    return re.sub(r"\s+", " ", s).strip()


def _index(taxonomy: Taxonomy) -> tuple[dict[str, list[str]], list[tuple[str, list[str]]]]:
    """(exact name -> ids, [(alias >= 3 chars, id)] longest first). Same normaliser as the input."""
    exact: dict[str, list[str]] = {}
    for cid in sorted(taxonomy.concepts):
        c = taxonomy.concepts[cid]
        for name in (c.label_fa, c.label_en, *c.aliases):
            n = taxonomy_module.normalize_text(clean_text(name))
            if n:
                ids = exact.setdefault(n, [])
                if cid not in ids:
                    ids.append(cid)
    sub = sorted(((n, cid) for n, cid in exact.items() if len(n) >= 3), key=lambda x: (-len(x[0]), x[0]))
    return exact, sub


@lru_cache(maxsize=2048)
def _alias_pattern(alias: str) -> re.Pattern[str]:
    # Cache by alias text, not taxonomy object ID. Only taxonomy labels enter here.
    return re.compile(rf"(?<![\w]){re.escape(alias)}(?![\w])")


def map_text_skills(texts: list[str], taxonomy: Taxonomy) -> list[str]:
    """Map posting sentences to all matching concepts, including shared aliases.

    Exact match first, then every alias (>= 3 chars) found as whole words inside the text.
    Unknown skills are dropped. Return unique ids, order preserved.
    """
    exact, sub = _index(taxonomy)
    patterns = [(_alias_pattern(alias), cids) for alias, cids in sub]
    out: list[str] = []
    for raw in texts:
        text = taxonomy_module.normalize_text(clean_text(raw))
        if not text:
            continue
        if text in exact:
            found = exact[text]
        else:
            # pos in text keeps the order of mention; an alias inside an already-matched longer one is skipped
            hits: list[tuple[int, str]] = []
            taken: list[tuple[int, int]] = []
            for pattern, cids in patterns:
                m = pattern.search(text)
                if m and not any(a <= m.start() and m.end() <= b for a, b in taken):
                    taken.append((m.start(), m.end()))
                    hits.extend((m.start(), cid) for cid in cids)
            found = [cid for _, cid in sorted(hits)]
        for cid in found:
            if cid not in out:
                out.append(cid)
    return out
