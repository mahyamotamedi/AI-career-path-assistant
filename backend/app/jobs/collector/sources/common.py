"""Field-mapping helpers shared by the source adapters (pure functions, no network)."""
import re

import jdatetime

from app.jobs.normalize import clean_text, normalize_text

CITIES = {
    "tehran": "تهران", "isfahan": "اصفهان", "esfahan": "اصفهان", "shiraz": "شیراز", "mashhad": "مشهد",
    "tabriz": "تبریز", "karaj": "کرج", "qom": "قم", "ahvaz": "اهواز", "rasht": "رشت", "kermanshah": "کرمانشاه",
    "urmia": "ارومیه", "yazd": "یزد", "kish": "کیش", "kerman": "کرمان", "hamedan": "همدان", "arak": "اراک",
}

_SENIOR = r"(ارشد|سنیور|senior|sr|لید|lead|مدیر|manager|head)"
_MID = r"(میان ?رده|میان‌رده|mid|intermediate)"
_JUNIOR = r"(کارآموز|کارامووز|جونیور|جونیر|junior|jr|intern|تازه ?کار)"
_NUM_WORDS = {"بدون": 0, "یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6, "هفت": 7, "هشت": 8, "نه": 9, "ده": 10}
_NEGATION = re.compile(r"(وجود ندارد|ندارد|نیست|ممکن نیست|not|no )")
_REMOTE = re.compile(r"(دور ?کاری|remote)")


def _has(pattern: str, text: str) -> bool:
    return re.search(rf"(?<![\w]){pattern}(?![\w])", text) is not None


def canonical_city(location: str) -> str:
    """'تهران، ونک' -> 'تهران'; 'Tehran, Iran' -> 'تهران'."""
    first = re.split(r"[،,\-–/|]", clean_text(location))[0].strip()
    return CITIES.get(first.lower(), first)


def detect_remote(text: str) -> bool:
    """True if the text offers remote work; 'امکان دورکاری وجود ندارد' (not possible) is False."""
    t = normalize_text(text)
    for m in _REMOTE.finditer(t):
        window = t[max(0, m.start() - 25): m.end() + 30].split(".")[0]
        if not _NEGATION.search(window):
            return True
    return False


def years_from_text(text: str) -> int | None:
    """Minimum years in 'سه تا شش سال' / '2-4 years' / 'بدون سابقه' -> 3 / 2 / 0."""
    t = normalize_text(text)
    if "بدون" in t and "سابقه" in t:
        return 0
    m = re.search(r"(\d+)", t)
    if m:
        return int(m.group(1))
    for word, n in _NUM_WORDS.items():
        if _has(word, t) and "سال" in t:
            return n
    return None


def detect_seniority(title: str, years: int | None = None) -> str | None:
    t = normalize_text(title)
    for level, pat in (("junior", _JUNIOR), ("mid", _MID), ("senior", _SENIOR)):
        if _has(pat, t):
            return level
    if years is None:
        return None
    return "junior" if years <= 2 else "mid" if years <= 5 else "senior"


def jalali_to_iso(text: str) -> str | None:
    """'1405/07/20' -> '2026-10-12'. Returns None if no Jalali date is found."""
    m = re.search(r"(1[34]\d{2})[/-](\d{1,2})[/-](\d{1,2})", normalize_text(text))
    if not m:
        return None
    try:
        return jdatetime.date(*map(int, m.groups())).togregorian().isoformat()
    except ValueError:
        return None


def clean_lines(lines: list[str], limit: int = 15) -> list[str]:
    """Strip bullets/whitespace, drop empties and over-long paragraphs, de-duplicate, cap."""
    out: list[str] = []
    for line in lines:
        s = clean_text(line)
        s = re.sub(r"^(?:[\s\-–•·*▪●■✓✔]+|\d+[.)]\s*)+", "", s).strip(" :؛;")
        if len(s) < 2 or len(s) > 160 or s in out:
            continue
        out.append(s)
    return out[:limit]
