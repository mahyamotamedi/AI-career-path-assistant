"""Module B end-to-end and Review Focus edge cases. The LLM extraction is stubbed with a
hand-written JSON answer (no gateway key in CI); text extraction, skill mapping, ranking, filters
and the API run for real."""
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.jobs import ranking
from app.jobs.resume_parser import ResumeExtraction
from app.llm import client
from app.llm.client import LLMResult
from app.main import app
from app.schemas import ResumeProfile
from app.session import get_session
from tests.test_ranking import fake_embed  # hashed bag-of-words vectors, no network

HIDDEN = Path(__file__).parent / "data" / "hidden_check.docx"  # junior React dev: not one of the 3 eval resumes


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(ranking, "_cache_path", lambda: tmp_path / "embeddings.npz")
    monkeypatch.setattr(ranking, "embed", fake_embed)


def fake_extraction(monkeypatch):
    data = ResumeExtraction(
        skills=["React", "JavaScript", "TypeScript", "HTML و CSS", "Git", "طراحی ریسپانسیو", "REST API"],
        years_experience=0.7, education=["BSc Software Engineering"], previous_roles=["Front-End intern"],
        location="Tehran", level_guess="junior")
    monkeypatch.setattr(client, "chat_json", lambda *a, **k: LLMResult(True, data=data))


def test_hidden_resume_end_to_end(monkeypatch, caplog):
    fake_extraction(monkeypatch)
    c = TestClient(app)
    with caplog.at_level(logging.INFO):
        r = c.post("/api/resume", data={"session_id": "hid"}, files={"file": ("cv.docx", HIDDEN.read_bytes())})
        assert r.status_code == 200
        skill_ids = r.json()["skill_ids"]
        assert {"frontend_framework", "javascript_basics", "typescript"} <= set(skill_ids)
        for method in ("baseline", "hybrid"):
            top = c.post("/api/jobs/match", json={"session_id": "hid", "method": method}).json()
            assert len(top) == 10
            titles = " ".join(m["posting"]["title"].lower() for m in top[:5])
            assert "react" in titles or "front" in titles, (method, titles)
        f = c.post("/api/jobs/match", json={"session_id": "hid", "method": "hybrid",
                                            "filters": {"location": "تهران", "seniority": "junior"}}).json()
        assert f and all(m["posting"]["seniority"] == "junior" and m["posting"]["location"] == "تهران" for m in f)
    assert "STUB" not in caplog.text


@pytest.mark.parametrize("method", ["baseline", "hybrid"])
def test_zero_matched_skills_still_returns_ranked_list(method):
    get_session("zero").resume = ResumeProfile(skills=["اوریگامی"], skill_ids=[], years_experience=0, level_guess=None)
    r = TestClient(app).post("/api/jobs/match", json={"session_id": "zero", "method": method})
    assert r.status_code == 200 and len(r.json()) == 10
    assert all(m["matched_skills"] == [] for m in r.json())


@pytest.mark.parametrize("method", ["baseline", "hybrid"])
def test_filters_matching_nothing_return_empty_list(method):
    get_session("empty").resume = ResumeProfile(skills=["Python"], skill_ids=["python_basics"], level_guess="junior")
    r = TestClient(app).post("/api/jobs/match", json={"session_id": "empty", "method": method,
                                                       "filters": {"location": "تبریز", "remote": True}})
    assert r.status_code == 200 and r.json() == []
