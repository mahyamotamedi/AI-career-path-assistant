"""Fixtures and fixture-backed endpoints must satisfy the shared contracts."""
import json

from fastapi.testclient import TestClient

from app.config import settings
from app.jobs.store import load_postings
from app.main import app
from app.schemas import CareerProfile, JobMatch, ResumeProfile, Roadmap

client = TestClient(app)
FIX = settings.data_dir / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_fixtures_match_schemas():
    CareerProfile(**_load("career_profile.json"))
    Roadmap(**_load("roadmap.json"))
    ResumeProfile(**_load("resume_profile.json"))
    [JobMatch(**m) for m in _load("job_matches.json")]


def test_fixture_postings_load():
    assert len(load_postings()) >= 5


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_chat_real_p2_failure_is_safe():
    # No keys/configuration: P2 must visibly fail, never complete through fixtures.
    r = client.post("/api/chat", json={"session_id": "t1", "message": "سلام"})
    assert r.status_code == 200 and not r.json()["done"]
    assert r.json()["profile"] is None and r.json()["questions_asked"] == 0


def test_chat_reaches_done_with_mocked_observation(p1_boundary, monkeypatch):
    from app.careers import conversation
    from app.llm.client import LLMResult
    observation = conversation.Observation(target_role="recruiter", target_level="junior",
                                           beginner=True, knowledge_complete=True)
    monkeypatch.setattr(conversation.client, "chat_json", lambda *a, **kw: LLMResult(True, observation))
    result = client.post("/api/chat", json={"session_id":"chat-success", "message":"مبتدی هستم"})
    assert result.json()["done"] and result.json()["profile"]["target_role"] == "recruiter"


def test_roadmap_endpoint_matches_real_p1(caplog):
    from app.careers.graph import compute_roadmap
    profile = CareerProfile(**_load("career_profile.json"))
    result = client.post("/api/roadmap", json=profile.model_dump())
    assert result.status_code == 200 and result.json() == compute_roadmap(profile).model_dump()
    assert "STUB" not in caplog.text


def test_resume_then_match_p3_boundary(monkeypatch):
    from app.jobs import resume_parser, ranking
    from app.llm.client import LLMResult
    monkeypatch.setattr(resume_parser.client, "chat_json", lambda sid, messages, schema, **kw:
                        LLMResult(True, schema(skills=["Python", "SQL"], years_experience=0)))
    matches = [JobMatch(**m) for m in _load("job_matches.json")]
    monkeypatch.setattr(ranking, "hybrid_rank", lambda *a, **kw: matches)
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Python SQL")
    files = {"file": ("cv.pdf", doc.tobytes(), "application/pdf")}
    assert client.post("/api/resume", data={"session_id": "t2"}, files=files).status_code == 200
    r = client.post("/api/jobs/match", json={"session_id": "t2", "method": "hybrid"})
    assert r.status_code == 200 and len(r.json()) >= 1


def test_match_without_resume_is_400():
    assert client.post("/api/jobs/match", json={"session_id": "nobody"}).status_code == 400


def test_usage_starts_at_zero():
    assert client.get("/api/usage/fresh").json()["calls"] == 0
