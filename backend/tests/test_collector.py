"""Offline parser tests on trimmed real samples (tests/data). Fetcher tests: test_fetcher.py."""
import json
from pathlib import Path

from app.jobs.collector.sources import common, jobinja, jobvision
from app.schemas import JobPosting

DATA = Path(__file__).parent / "data"


def test_jobinja_parse_list_strips_tracking():
    urls = jobinja.parse_list((DATA / "jobinja_list.html").read_text("utf-8"))
    assert len(urls) == 2
    assert all(u.startswith("https://jobinja.ir/companies/") and "?" not in u for u in urls)


def test_jobinja_parse_detail():
    url = (DATA / "jobinja_detail.url").read_text().strip()
    p = jobinja.parse_detail((DATA / "jobinja_detail.html").read_text("utf-8"), url)
    assert isinstance(p, JobPosting)
    assert p.id.startswith("jobinja-") and p.url == url
    assert p.title and p.company and p.location == "تهران"
    assert "python_basics" in p.skill_ids
    assert p.seniority == "mid"  # 'سه تا شش سال' -> min 3 years
    assert p.remote is False  # text says remote work is NOT possible
    assert p.published_at and len(p.requirements) <= 15


def test_jobinja_detail_without_title_is_skipped():
    assert jobinja.parse_detail("<html></html>", "https://jobinja.ir/companies/x/jobs/abc/y") is None


def test_jobvision_parse_list():
    items = jobvision.parse_list(json.loads((DATA / "jobvision_list.json").read_text("utf-8")))
    assert len(items) == 2 and items[0]["id"] == 1586860 and items[0]["years"] == 3


def test_jobvision_parse_detail():
    html = (DATA / "jobvision_detail.html").read_text("utf-8")
    p = jobvision.parse_detail(html, 1586860, years=3)
    assert p is not None and p.id == "jobvision-1586860"
    assert p.url.startswith("https://jobvision.ir/jobs/1586860")
    assert p.location == "تهران" and p.seniority == "mid"
    assert {"python_basics", "backend_framework"} <= set(p.skill_ids)
    assert not any("وام" in r for r in p.requirements)  # benefits section excluded
    assert jobvision.parse_detail(html, 999) is None  # wrong id -> no detail state


def test_common_helpers():
    assert common.canonical_city("تهران، ونک") == "تهران"
    assert common.canonical_city("Tehran") == "تهران"
    assert common.detect_remote("امکان دورکاری وجود دارد") and common.detect_remote("Remote friendly")
    assert not common.detect_remote("امکان دور کاری وجود ندارد.")
    assert common.detect_seniority("Senior Data Analyst") == "senior"
    assert common.detect_seniority("کارآموز تولید محتوا") == "junior"
    assert common.detect_seniority("دستیار مدیر محصول") == "junior"  # assistant outranks مدیر
    assert common.detect_seniority("Assistant Product Manager", years=7) == "junior"
    assert common.detect_seniority("مدیر محصول") == "senior"
    assert common.detect_seniority("برنامه‌نویس", years=4) == "mid"
    assert common.detect_seniority("برنامه‌نویس") is None
    assert common.years_from_text("سه تا شش سال") == 3 and common.years_from_text("بدون سابقه") == 0
    assert common.jalali_to_iso("1405/07/20") == "2026-10-12"


def test_unmapped_report_uses_sentence_skills():
    from scripts.collect_jobs import unmapped_phrases
    p = JobPosting(id="sentence", source="test", title="Analyst", company="test", location="تهران",
                   requirements=["تسلط به SQL و Power BI", "xyzzy"], url="https://example.test/job")
    assert unmapped_phrases([p]) == [("xyzzy", 1)]
