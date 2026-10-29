"""Plan reconciliation checks using the merged P1 taxonomy and real graph engine.

Only model extraction is mocked; these tests must never use fixture roadmaps.
"""
from fastapi.testclient import TestClient

from app.careers import conversation, graph
from app.careers.taxonomy import ancestors, get_taxonomy
from app.jobs.normalize import map_skills
from app.llm.client import LLMResult
from app.main import app
from app.schemas import CareerProfile
from app.session import get_session

client = TestClient(app)


def mock_observation(monkeypatch, **values):
    observation = conversation.Observation(**values)
    monkeypatch.setattr(conversation.client, "chat_json", lambda *a, **kw: LLMResult(True, observation))


def test_merged_taxonomy_mapping_uses_current_aliases():
    tax = get_taxonomy()
    assert len(tax.roles) >= 10 and "recruiter" in tax.roles
    assert map_skills(["پايتون", "Python", "اكسل", "unknown skill"], tax) == ["python_basics", "excel"]
    # IDs and actual live aliases must point to the same current concept, without an old mapping.
    for cid, concept in tax.concepts.items():
        assert map_skills([cid], tax) == [cid]
        assert set(map_skills(concept.aliases, tax)) <= {cid}


def test_chat_and_repeated_correction_with_real_graph(monkeypatch, caplog):
    mock_observation(monkeypatch, target_role="تحلیلگر داده", target_level="junior", beginner=True,
                     knowledge_complete=True, skills=[
                         {"skill":"اكسل", "status":"known", "evidence":"اكسل بلدم"},
                         {"skill":"SQL", "status":"heard", "evidence":"SQL فقط شنیدم"},
                     ])
    result = client.post("/api/chat", json={"session_id":"plan", "message":"اكسل بلدم و SQL فقط شنیدم"})
    assert result.status_code == 200 and result.json()["done"]
    profile = CareerProfile.model_validate(result.json()["profile"])
    assert profile.target_role == "data_analyst" and profile.heard_of_only == ["sql_basics"]
    expected = graph.compute_roadmap(profile, get_taxonomy())
    roadmap = client.post("/api/roadmap", json=profile.model_dump())
    assert roadmap.json() == expected.model_dump()
    assert any(n["id"] == "excel" and n["status"] == "known" for n in roadmap.json()["nodes"])

    mock_observation(monkeypatch, skills=[{"skill":"excel", "status":"unknown", "evidence":"اکسل بلد نیستم"}])
    payload = {"session_id":"plan", "message":"من اکسل بلد نیستم"}
    first = client.post("/api/roadmap/correct", json=payload)
    second = client.post("/api/roadmap/correct", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert any(n["id"] == "excel" and n["status"] == "todo" for n in first.json()["nodes"])
    stored = get_session("plan").profile
    assert "excel" not in ancestors(get_taxonomy().concepts, stored.known_concepts)
    assert first.json()["summary_fa"] == graph.compute_roadmap(stored).summary_fa
    assert "STUB" not in caplog.text


def test_real_prerequisite_conflict_does_not_commit(monkeypatch, caplog):
    session = get_session("conflict")
    session.profile = CareerProfile(target_role="data_analyst", target_level="mid", current_level="junior",
                                    known_concepts=["pivot_tables", "python_basics"])
    tax = get_taxonomy()
    assert "excel" in ancestors(tax.concepts, session.profile.known_concepts)
    original = session.profile.model_copy(deep=True)
    before = graph.compute_roadmap(original)
    mock_observation(monkeypatch, skills=[{"skill":"excel", "status":"unknown", "evidence":"اکسل بلد نیستم"}])
    result = client.post("/api/roadmap/correct", json={"session_id":"conflict", "message":"اکسل بلد نیستم"})
    assert result.status_code == 422 and session.profile == original
    assert graph.compute_roadmap(session.profile) == before
    assert "STUB" not in caplog.text
