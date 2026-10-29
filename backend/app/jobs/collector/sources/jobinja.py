"""jobinja.ir adapter: server-rendered HTML. Keyword listing pages -> detail pages (+ JSON-LD)."""
import json
import logging
import re
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup

from app.careers.taxonomy import get_taxonomy
from app.jobs.collector.base import PoliteFetcher
from app.jobs.collector.sources import common
from app.jobs.normalize import clean_text, map_text_skills, normalize_text
from app.schemas import JobPosting

log = logging.getLogger(__name__)

SOURCE = "jobinja"
BASE = "https://jobinja.ir"
CAP = 40
# one keyword per taxonomy area so the sample spans software, data, business and marketing
KEYWORDS = [
    "python", "react", "devops", "تحلیلگر داده", "data engineer", "یادگیری ماشین",
    "مدیر محصول", "تحلیلگر مالی", "سئو", "بازاریابی دیجیتال", "جذب و استخدام",
]
_HEADING = re.compile(r"(مهارت|شرایط|الزامات|نیازمندی|توانایی|مورد نیاز|requirements|skills)")


def list_url(keyword: str) -> str:
    return f"{BASE}/jobs?filters%5Bkeywords%5D%5B0%5D={quote(keyword)}&page=1"


def parse_list(html: str) -> list[str]:
    """Detail-page URLs (tracking query stripped) from a listing page, in page order."""
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    for a in soup.select("a.c-jobListView__titleLink[href]"):
        u = a["href"].split("?")[0]
        if u not in urls:
            urls.append(u)
    return urls


def _site_id(url: str) -> str | None:
    m = re.search(r"/jobs/([A-Za-z0-9]+)/", urlsplit(url).path + "/")
    return m.group(1) if m else None


def _info_box(soup: BeautifulSoup) -> dict[str, list[str]]:
    info: dict[str, list[str]] = {}
    for li in soup.select("li.c-infoBox__item"):
        h = li.select_one(".c-infoBox__itemTitle")
        if h:
            info[normalize_text(h.get_text())] = [s.get_text(" ", strip=True) for s in li.select(".tags span")]
    return info


def _description_lines(soup: BeautifulSoup) -> tuple[list[str], list[str]]:
    """(requirement-section lines, all lines) of the job description."""
    box = soup.select_one(".s-jobDesc")
    if box is None:
        return [], []
    for br in box.find_all("br"):
        br.replace_with("\n")
    for li in box.find_all("li"):
        li.insert_before("\n")
    lines = [l.strip() for l in box.get_text("\n").split("\n") if l.strip()]
    lines = [l for l in lines if "ثبت آگهی استخدام" not in l]
    section: list[str] = []
    active = False
    for l in lines:
        is_heading = l.rstrip().endswith(":") and len(l) < 60
        if is_heading:
            active = bool(_HEADING.search(normalize_text(l)))
            continue
        if active:
            section.append(l)
    return section, lines


def parse_detail(html: str, url: str) -> JobPosting | None:
    soup = BeautifulSoup(html, "lxml")
    site_id = _site_id(url)
    h1 = soup.select_one("h1")
    ld: dict = {}
    tag = soup.select_one("script[type='application/ld+json']")
    if tag and tag.string:
        try:
            ld = json.loads(tag.string)
        except ValueError:
            pass
    title = clean_text(re.sub(r"^\s*استخدام\s+", "", h1.get_text(" ", strip=True))) if h1 else ""
    if not (site_id and title and url):
        return None
    info = _info_box(soup)
    company = clean_text(((ld.get("hiringOrganization") or {}).get("name") or "").split("|")[0])
    if not company:
        a = soup.select_one("a[href*='/companies/'] h2, .c-companyHeader__name")
        company = clean_text(a.get_text()) if a else ""
    location = common.canonical_city(" ".join(info.get("موقعیت مکانی", [])[:1]) or "")
    section, lines = _description_lines(soup)
    skill_tags = info.get("مهارت‌های مورد نیاز") or info.get(normalize_text("مهارت‌های مورد نیاز")) or []
    requirements = common.clean_lines(skill_tags + (section or lines))
    years = common.years_from_text(" ".join(info.get(normalize_text("حداقل سابقه کار"), [])))
    tax = get_taxonomy()
    try:
        return JobPosting(
            id=f"{SOURCE}-{site_id}", source=SOURCE, title=title, company=company or "نامشخص",
            location=location or "نامشخص",
            remote=common.detect_remote(" ".join(lines) + " " + title),
            seniority=common.detect_seniority(title, years),
            requirements=requirements,
            skill_ids=map_text_skills(requirements + [title], tax),
            published_at=ld.get("datePosted") or None,
            url=url,
        )
    except ValueError as e:
        log.warning("skip %s: %s", url, e)
        return None


def fetch(fetcher: PoliteFetcher, cap: int = CAP) -> list[JobPosting]:
    per_kw = -(-cap // len(KEYWORDS))
    out: list[JobPosting] = []
    seen: set[str] = set()
    for kw in KEYWORDS:
        html = fetcher.get(list_url(kw))
        if html is None:
            log.warning("jobinja: listing %r unavailable", kw)
            continue
        taken = 0
        for url in parse_list(html):
            if len(out) >= cap or taken >= per_kw:
                break
            if url in seen:
                continue
            seen.add(url)
            page = fetcher.get(url)
            posting = parse_detail(page, url) if page else None
            if posting is None:
                log.warning("jobinja: skipped %s", url)
                continue
            out.append(posting)
            taken += 1
    return out
