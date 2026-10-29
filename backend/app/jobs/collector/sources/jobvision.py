"""jobvision.ir adapter.

Listing: POST JSON to candidateapi.jobvision.ir/api/v1/JobPost/List (the only path that host's
robots.txt allows; no query string). Detail: the public, server-rendered page jobvision.ir/jobs/<id>
(allowed by jobvision.ir/robots.txt), whose embedded `ng-state` JSON holds the description.
The API's own JobPost/Detail endpoint is disallowed by robots.txt and is never called.
"""
import json
import logging
import re
from html import unescape
from typing import Any

from bs4 import BeautifulSoup

from app.careers.taxonomy import get_taxonomy
from app.jobs.collector.base import PoliteFetcher
from app.jobs.collector.sources import common
from app.jobs.normalize import clean_text, map_text_skills
from app.schemas import JobPosting

log = logging.getLogger(__name__)

SOURCE = "jobvision"
LIST_URL = "https://candidateapi.jobvision.ir/api/v1/JobPost/List"
PAGE_URL = "https://jobvision.ir/jobs/{id}"
CAP = 40
LISTING_TTL_S = 3600  # list responses go stale after 1 h (incremental refresh); detail pages stay cached
KEYWORDS = [
    "python", "react", "devops", "تحلیلگر داده", "مهندس داده", "یادگیری ماشین",
    "مدیر محصول", "تحلیلگر مالی", "سئو", "بازاریابی دیجیتال", "کارشناس جذب",
]
_SKIP_SECTION = re.compile(r"(مزایا|درباره|benefits|about)")


def parse_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """[{id, years}] from a JobPost/List response."""
    posts = ((payload or {}).get("data") or {}).get("jobPosts") or []
    return [
        {"id": p["id"], "years": (p.get("properties") or {}).get("requiredRelatedExperienceYears")}
        for p in posts if p.get("id")
    ]


def _state(html: str, job_id: int) -> dict[str, Any] | None:
    m = re.search(r'<script id="ng-state"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        state = json.loads(m.group(1))
    except ValueError:
        return None
    for key, val in state.items():
        if f"JobPost/Detail?jobPostId={job_id}" in key and isinstance(val, dict):
            return val.get("data", val)
    return None


def _description_items(description_html: str) -> list[str]:
    """<li> items grouped by the preceding <strong>heading:</strong>, minus benefits/about sections."""
    soup = BeautifulSoup(description_html or "", "lxml")
    items: list[str] = []
    for ul in soup.find_all(["ul", "ol"]):
        heading = ""
        for prev in ul.previous_siblings:
            txt = getattr(prev, "get_text", lambda *a, **k: str(prev))(" ", strip=True)
            if txt:
                heading = txt[-80:]
                break
        if _SKIP_SECTION.search(heading):
            continue
        items.extend(li.get_text(" ", strip=True) for li in ul.find_all("li"))
    return items


def parse_detail(html: str, job_id: int, years: int | None = None) -> JobPosting | None:
    d = _state(html, job_id)
    if not d:
        return None
    title = clean_text(d.get("title") or "")
    canon = re.search(r'<link rel="canonical" href="([^"]+)"', html)
    url = unescape(canon.group(1)) if canon else PAGE_URL.format(id=job_id)
    if not (title and url):
        return None
    company_names = (d.get("company") or {}).get("name") or {}
    company = clean_text(company_names.get("titleFa") or company_names.get("titleEn") or "")
    loc = d.get("location") or {}
    city = (loc.get("city") or {}).get("titleFa") or (loc.get("province") or {}).get("titleFa") or ""
    text = BeautifulSoup(d.get("description") or "", "lxml").get_text(" ", strip=True)
    software = [
        clean_text(((s.get("software") or {}).get("titleFa") or "")) for s in d.get("softwareRequirements") or []
    ]
    skills = [clean_text(((s.get("skill") or s).get("titleFa") or "")) for s in d.get("skills") or []]
    requirements = common.clean_lines([s for s in software + skills if s] + _description_items(d.get("description") or ""))
    if years is None:
        years = d.get("requiredRelatedExperienceYears")
    seniority = common.detect_seniority(title, years)
    if seniority is None and d.get("isInternship"):
        seniority = "junior"
    published = (d.get("activationTime") or {}).get("date") or ""
    try:
        return JobPosting(
            id=f"{SOURCE}-{job_id}", source=SOURCE, title=title, company=company or "نامشخص",
            location=common.canonical_city(city) or "نامشخص",
            remote=bool(d.get("isRemote")) or common.detect_remote(text),
            seniority=seniority, requirements=requirements,
            skill_ids=map_text_skills(requirements + [title], get_taxonomy()),
            published_at=published[:10] or None, url=url,
        )
    except ValueError as e:
        log.warning("skip jobvision %s: %s", job_id, e)
        return None


def fetch(fetcher: PoliteFetcher, cap: int = CAP) -> list[JobPosting]:
    per_kw = -(-cap // len(KEYWORDS))
    out: list[JobPosting] = []
    seen: set[int] = set()
    for kw in KEYWORDS:
        raw = fetcher.post_json(LIST_URL, {"pageSize": per_kw + 4, "requestedPage": 1, "keyword": kw, "sortBy": 1},
                                max_age_s=LISTING_TTL_S)
        if raw is None:
            log.warning("jobvision: list %r unavailable (blocked or failed)", kw)
            continue
        try:
            items = parse_list(json.loads(raw))
        except ValueError:
            log.warning("jobvision: list %r not JSON", kw)
            continue
        taken = 0
        for item in items:
            if len(out) >= cap or taken >= per_kw:
                break
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            page = fetcher.get(PAGE_URL.format(id=item["id"]))
            posting = parse_detail(page, item["id"], item["years"]) if page else None
            if posting is None:
                log.warning("jobvision: skipped %s", item["id"])
                continue
            out.append(posting)
            taken += 1
    return out
