import httpx
import pytest

from app.config import settings
from app.jobs.collector import base
from app.jobs.collector.base import PoliteFetcher, Robots

UA = "TestBot/1.0 (contact: x@example.com)"
JV = "user-agent: *\ndisallow: *?*\ndisallow: */Login/*\nAllow: *.js\nAllow: *.css\n"


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(settings, "scraper_min_delay_s", 0.0)


def make_fetcher(tmp_path, handler):
    f = PoliteFetcher(cache_dir=tmp_path)
    f._client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": UA})
    return f


def test_wildcard_robots_jobvision_rules():
    r = Robots(JV, UA)
    assert not r.can_fetch("https://jobvision.ir/jobs?page=2")
    assert r.can_fetch("https://jobvision.ir/jobs")
    assert r.can_fetch("https://jobvision.ir/static/app.js")
    assert not r.can_fetch("https://jobvision.ir/Login/x")


def test_robots_longest_rule_wins_and_allow_wins_ties():
    r = Robots("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /c$\nAllow: /c$\n", UA)
    assert not r.can_fetch("https://h/a/x")
    assert r.can_fetch("https://h/a/b/x")
    assert r.can_fetch("https://h/c")
    assert Robots("User-agent: *\nDisallow:\n", UA).can_fetch("https://h/anything")


def test_respects_robots_disallow(tmp_path):
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, text="ok")

    f = make_fetcher(tmp_path, handler)
    assert f.get("https://site.test/private/x") is None
    assert "/private/x" not in seen
    assert f.get("https://site.test/public") == "ok"


def test_min_delay_between_requests_per_host(tmp_path, monkeypatch):
    clock = {"t": 100.0}
    sleeps = []
    monkeypatch.setattr(base.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(base.time, "sleep", lambda s: (sleeps.append(s), clock.__setitem__("t", clock["t"] + s)))
    monkeypatch.setattr(settings, "scraper_min_delay_s", 3.0)
    f = make_fetcher(tmp_path, lambda req: httpx.Response(200, text="x"))
    f.get("https://a.test/1")
    f.get("https://a.test/2")
    f.get("https://b.test/1")  # other host: robots + page, first contact, no wait
    gaps = [round(s, 6) for s in sleeps]
    assert gaps and all(g == 3.0 for g in gaps)
    assert len(gaps) == 3  # a: robots->page1, page1->page2 ; b: robots->page


def test_user_agent_sent(tmp_path):
    uas = []

    def handler(req):
        uas.append(req.headers["user-agent"])
        return httpx.Response(200, text="User-agent: *\nDisallow:\n")

    f = make_fetcher(tmp_path, handler)
    f.get("https://site.test/x")
    f.post_json("https://site.test/api", {"a": 1})
    assert uas and all(u == UA for u in uas)


def test_post_json_blocked_by_robots(tmp_path):
    f = make_fetcher(tmp_path, lambda req: httpx.Response(200, text="User-agent: *\nDisallow: /api\n"))
    assert f.post_json("https://site.test/api", {}) is None
