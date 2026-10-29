"""B-11 incremental refresh: cache TTL, upsert/expiry, failing source, lock, atomic write. No network."""
import os
import time
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.jobs import store
from app.jobs.collector.base import PoliteFetcher
from app.schemas import JobPosting
from scripts import collect_jobs as cj


@pytest.fixture(autouse=True)
def tmp_data(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "scraper_min_delay_s", 0.0)
    (tmp_path / "jobs").mkdir()


def jp(id, title="Data Analyst", source="a", date_="2026-10-20", company=None, reqs=()):
    return JobPosting(id=f"{source}-{id}", source=source, title=title, company=company or f"co-{id}", location="تهران",
                      published_at=date_, url=f"https://x.test/{source}/{id}", requirements=list(reqs))


def test_listing_cache_expires_after_max_age_but_detail_cache_does_not(tmp_path):
    hits = []

    def handler(req):
        hits.append(req.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow:\n" if req.url.path == "/robots.txt" else "body")

    f = PoliteFetcher(cache_dir=tmp_path / "raw")
    f._client = httpx.Client(transport=httpx.MockTransport(handler))
    f.get("https://s.test/list", max_age_s=3600)
    f.get("https://s.test/list", max_age_s=3600)
    assert hits.count("/list") == 1  # fresh -> cached
    old = time.time() - 7200
    os.utime(f._cache_path("https://s.test/list"), (old, old))
    f.get("https://s.test/list", max_age_s=3600)
    assert hits.count("/list") == 2  # older than the TTL -> refetched
    f.get("https://s.test/detail")
    os.utime(f._cache_path("https://s.test/detail"), (old, old))
    f.get("https://s.test/detail")  # no max age: cached forever
    assert hits.count("/detail") == 1


def test_merge_upserts_by_id_new_data_wins():
    old = [jp("1", reqs=["a"]), jp("2", title="Backend Dev")]
    new = {"a": [jp("1", reqs=["a", "b"]), jp("3", title="SEO Expert")]}
    out = {p.id: p for p in cj.merge_incremental(old, new, today=date(2026, 10, 29))}
    assert set(out) == {"a-1", "a-2", "a-3"} and out["a-1"].requirements == ["a", "b"]


def test_merge_expires_old_postings_and_keeps_undated():
    old = [jp("old", date_="2026-07-01", title="Old role"), jp("undated", date_=None, title="Other role"), jp("new", title="New role")]
    out = {p.id for p in cj.merge_incremental(old, {}, today=date(2026, 10, 29))}
    assert out == {"a-undated", "a-new"}


def test_failing_source_keeps_its_old_postings():
    old = [jp("1", source="a", title="Role A"), jp("2", source="b", title="Role B")]
    out = {p.id for p in cj.merge_incremental(old, {"a": [], "b": [jp("9", source="b", title="Role C")]}, today=date(2026, 10, 29))}
    assert out == {"a-1", "b-2", "b-9"}  # source a returned nothing -> kept


def test_merge_dedups_across_sources():
    a, b = jp("1", source="a", company="X"), jp("1", source="b", company="X")
    assert len(cj.merge_incremental([], {"a": [a], "b": [b]}, today=date(2026, 10, 29))) == 1


def test_lock_blocks_second_run_and_recovers_stale_lock():
    with cj.collect_lock() as first:
        assert first
        with cj.collect_lock() as second:
            assert not second
    with cj.collect_lock() as again:
        assert again  # released
    lock = settings.data_dir / "jobs" / ".collect.lock"
    lock.write_text("")
    old = time.time() - cj.LOCK_STALE_S - 10
    os.utime(lock, (old, old))
    with cj.collect_lock() as stale:
        assert stale  # a crashed run's stale lock is replaced


def test_save_postings_is_atomic():
    store.save_postings([jp("1")])
    before = store.postings_path().read_text("utf-8")

    class Boom(JobPosting):
        def model_dump_json(self, *a, **k):
            raise RuntimeError("disk full")

    with pytest.raises(RuntimeError):
        store.save_postings([jp("2"), Boom(**jp("3").model_dump())])
    assert store.postings_path().read_text("utf-8") == before  # old file untouched


def test_incremental_main_updates_and_survives_a_dead_source(monkeypatch, capsys):
    store.save_postings([jp("1", source="a", title="Role A"), jp("2", source="b", title="Role B")])
    ok = SimpleNamespace(SOURCE="a", fetch=lambda fetcher, cap=40: [jp("3", source="a", title="Role C", date_=date.today().isoformat())])

    def dead(fetcher, cap=40):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(cj, "SOURCES", [ok, SimpleNamespace(SOURCE="b", fetch=dead)])
    monkeypatch.setattr(cj, "summarize", lambda postings: None)  # summary reads the real taxonomy; not under test
    cj.main(incremental=True)
    ids = {p.id for p in store.load_postings()}
    assert "a-3" in ids and "b-2" in ids  # new posting added; the dead source keeps its old one
    assert "Incremental refresh" in capsys.readouterr().out
