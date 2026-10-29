from app.jobs.dedup import dedup
from app.schemas import JobPosting


def jp(id, title, company="دیجی‌کالا", location="تهران", reqs=(), date=None, url=None, source="a"):
    return JobPosting(id=id, source=source, title=title, company=company, location=location,
                      requirements=list(reqs), published_at=date, url=url or f"https://x.test/{id}")


def test_dedup_same_job_two_sources():
    a = jp("a-1", "برنامه‌نویس پایتون", reqs=["python"], source="a")          # ی Persian
    b = jp("b-1", "برنامه نويس پايتون", company="ديجي کالا", reqs=["python", "django", "git"], source="b")
    out = dedup([a, b])
    assert [p.id for p in out] == ["b-1"]  # keeps the one with more requirements


def test_dedup_keeps_distinct_jobs():
    posts = [
        jp("1", "Python Developer"),
        jp("2", "Data Analyst"),
        jp("3", "Python Developer", company="اسنپ"),
        jp("4", "Python Developer", location="شیراز"),
    ]
    assert len(dedup(posts)) == 4


def test_dedup_same_url_keeps_newer_when_equal_requirements():
    a = jp("1", "Data Analyst", date="2026-10-01", url="https://x.test/same")
    b = jp("2", "Other title", company="X", date="2026-10-20", url="https://x.test/same")
    out = dedup([a, b])
    assert [p.id for p in out] == ["2"]
