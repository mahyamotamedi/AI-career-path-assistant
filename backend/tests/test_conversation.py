"""P2 behavior tests with isolated model responses and taxonomy fixtures."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.careers import conversation as conv, taxonomy as tax_module, graph
from app.careers.taxonomy import Concept, Role, Taxonomy
from app.config import settings
from app.llm.client import LLMError, LLMResult
from app.llm.errors import P2Error
from app.main import app
from app.schemas import CareerProfile, Roadmap
from app.session import get_session

client = TestClient(app)


@pytest.fixture
def model(monkeypatch):
    outputs = []
    def call(*args, **kwargs):
        item = outputs.pop(0)
        return item if isinstance(item, LLMResult) else LLMResult(True, conv.Observation.model_validate(item))
    monkeypatch.setattr(conv.client, "chat_json", call)
    return outputs


def complete(**kw):
    return {"target_role": "recruiter", "target_level": "mid", "beginner": True, "knowledge_complete": True, **kw}


def skill(name, status, evidence):
    return {"skill": name, "status": status, "evidence": evidence}


def test_early_completion_and_harmless_retry(p1_boundary, model):
    model.append(complete(skills=[skill("excel", "heard", "شنیده‌ام")]))
    session = get_session("s")
    reply = conv.handle_message(session, "اکسل شنیده‌ام")
    assert reply.done and reply.questions_asked == 0
    assert reply.profile.current_level == "junior"
    assert reply.profile.known_concepts == [] and reply.profile.heard_of_only == ["excel"]
    assert conv.handle_message(session, "سلام").profile == reply.profile
    assert not get_session("other").profile


def test_six_question_cap_and_unsupported_role(p1_boundary, model, monkeypatch):
    monkeypatch.setattr(settings, "max_questions", 50)
    for _ in range(8):
        model.append({"target_role": "astronaut"})
        reply = conv.handle_message(get_session("s"), "فضانورد")
        assert not reply.done
    assert reply.questions_asked == 6 and "؟" not in reply.reply


def test_latest_negative_and_unknown_ids(p1_boundary, model):
    model.extend([{"skills": [skill("excel", "known", "بلدم"), skill("unapproved", "known", "بلدم")]},
                  complete(skills=[skill("excel", "unknown", "بلد نیستم")])])
    session = get_session("s")
    conv.handle_message(session, "اکسل بلدم")
    result = conv.handle_message(session, "اکسل بلد نیستم")
    assert result.done and result.profile.known_concepts == []


def test_contradiction_blocks_publication(p1_boundary, model):
    model.append(complete(skills=[skill("pivot_tables", "known", "پیوت بلدم"), skill("excel", "heard", "اکسل شنیدم")]))
    result = conv.handle_message(get_session("s"), "پیوت بلدم ولی اکسل شنیدم")
    assert not result.done and result.questions_asked == 1
    model.append({"skills": [skill("pivot_tables", "unknown", "پیوت بلد نیستم")]})
    assert conv.handle_message(get_session("s"), "پیوت بلد نیستم").done


def test_failure_preserves_state_and_retry_history(p1_boundary, model, caplog):
    session = get_session("s")
    model.extend([LLMResult(False, error=LLMError("timeout", "sanitized")), complete()])
    assert not conv.handle_message(session, "خصوصی").done
    assert session.history == [] and session.draft == {} and session.questions_asked == 0
    assert conv.handle_message(session, "خصوصی").done
    assert sum(h["role"] == "user" for h in session.history) == 1
    assert "خصوصی" not in caplog.text


def test_same_session_serialized(p1_boundary, model):
    model.append(complete())
    session = get_session("s")
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: conv.handle_message(session, "سلام"), range(2)))
    assert all(r.done for r in results) and len(session.history) == 2


def seeded_session():
    s = get_session("s")
    s.profile = CareerProfile(target_role="recruiter", target_level="mid", current_level="junior", known_concepts=["excel", "python_basics"])
    return s


def test_negative_and_positive_corrections(p1_boundary, model):
    s = seeded_session()
    original = s.profile.model_copy(deep=True)
    model.append({"skills": [skill("excel", "unknown", "بلد نیستم")]})
    candidate = conv.apply_correction(s, "اکسل بلد نیستم")
    assert candidate.known_concepts == ["python_basics"] and s.profile == original
    model.append({"skills": [skill("excel", "heard", "فقط شنیدم")]})
    heard = conv.apply_correction(s, "اکسل فقط شنیدم")
    assert "excel" not in heard.known_concepts and "excel" in heard.heard_of_only
    s.profile = candidate
    model.append({"skills": [skill("excel", "known", "بلدم")]})
    assert set(conv.apply_correction(s, "اکسل بلدم").known_concepts) == {"excel", "python_basics"}


def test_dependent_correction_rejected(p1_boundary, model):
    s = seeded_session()
    s.profile.known_concepts.append("pivot_tables")
    model.append({"skills": [skill("excel", "unknown", "بلد نیستم")]})
    with pytest.raises(P2Error):
        conv.apply_correction(s, "اکسل بلد نیستم")
    assert "excel" in s.profile.known_concepts


@pytest.mark.parametrize("error", [ValueError("private content"), RuntimeError("private content"), NotImplementedError()])
def test_router_rollback_before_stub(p1_boundary, model, monkeypatch, error):
    s = seeded_session()
    previous = s.profile.model_copy(deep=True)
    model.append({"skills": [skill("excel", "unknown", "بلد نیستم")]})
    def fail(*args):
        raise error
    monkeypatch.setattr(graph, "compute_roadmap", fail)
    result = client.post("/api/roadmap/correct", json={"session_id": "s", "message": "اکسل بلد نیستم"})
    assert result.status_code == (200 if isinstance(error, NotImplementedError) else 422)
    assert s.profile == previous and s.draft == {}
    assert "private" not in result.text


def test_endpoint_success_is_p2(p1_boundary, model, monkeypatch, caplog):
    model.append(complete())
    result = client.post("/api/chat", json={"session_id": "s", "message": "مبتدی هستم"})
    assert result.json()["done"] and result.json()["profile"]["target_role"] == "recruiter"
    # Explicitly mocked graph boundary; real P1 integration has a separate check below.
    monkeypatch.setattr(graph, "compute_roadmap", lambda p, tax: Roadmap(role=p.target_role, level=p.target_level, nodes=[], edges=[], order=[], summary_fa="خلاصهٔ تست"))
    model.append({"skills": [skill("excel", "unknown", "بلد نیستم")]})
    result = client.post("/api/roadmap/correct", json={"session_id": "s", "message": "اکسل بلد نیستم"})
    assert result.status_code == 200 and result.json()["summary_fa"] == "خلاصهٔ تست"
    assert "STUB" not in caplog.text


def test_real_p1_graph_integration(monkeypatch, caplog):
    from app.api import roadmap
    tax = tax_module.get_taxonomy()
    assert "recruiter" in tax.roles and "excel" in tax.concepts
    profile = CareerProfile(target_role="recruiter", target_level="junior", current_level="junior", known_concepts=["excel"])
    obs = complete(target_level="junior", skills=[skill("excel", "known", "اکسل بلدم")])
    monkeypatch.setattr(conv.client, "chat_json", lambda *a, **k: LLMResult(True, conv.Observation(**obs)))
    result = client.post("/api/chat", json={"session_id":"real", "message":"اکسل بلدم"})
    assert result.json()["done"]
    actual = graph.compute_roadmap(profile, tax)
    output = client.post("/api/roadmap", json=profile.model_dump())
    assert output.json()["summary_fa"] == actual.summary_fa
    negative = conv.Observation(skills=[conv.SkillObservation(**skill("excel", "unknown", "بلد نیستم"))])
    monkeypatch.setattr(conv.client, "chat_json", lambda *a, **k: LLMResult(True, negative))
    corrected = client.post("/api/roadmap/correct", json={"session_id":"real", "message":"اکسل بلد نیستم"})
    assert corrected.status_code == 200
    assert all(n["status"] == "todo" for n in corrected.json()["nodes"] if n["id"] == "excel")
    assert "STUB" not in caplog.text


@pytest.mark.parametrize("levels,expected", [
    ({}, ("junior", "junior")),
    ({"target_level": "senior"}, ("senior", "junior")),
    ({"current_level": "mid"}, ("junior", "mid")),
])
def test_question_cap_publishes_best_effort(p1_boundary, model, levels, expected):
    session = get_session("cap")
    for _ in range(6):
        model.append({"target_role": "recruiter", **levels})
        assert not conv.handle_message(session, "اطلاعاتی ندارم").done
    model.append({})
    result = conv.handle_message(session, "با همین اطلاعات شروع کنیم")
    assert result.done and result.questions_asked == session.questions_asked == 6
    assert (result.profile.target_level, result.profile.current_level) == expected
    assert result.profile.known_concepts == []
    assert "فرض شد" in result.reply and "junior" in result.reply
    assert conv.handle_message(session, "ادامه").profile == result.profile


def test_question_cap_without_role_offers_next_step(monkeypatch, model):
    tax = tax_module.get_taxonomy()
    session = get_session("role-cap")
    session.questions_asked = 6
    model.append({"target_role": "unsupported-role"})
    result = conv.handle_message(session, "نقش دلخواه")
    assert not result.done and result.profile is None and result.questions_asked == 6
    assert "در پیام بعد نام ببرید" in result.reply
    assert "unsupported-role" not in result.reply
    names = [r.label_fa for _, r in sorted(tax.roles.items())[:4]]
    assert len(names) == 4 and all(name in result.reply for name in names)
    model.append({"target_role": "recruiter"})
    continued = conv.handle_message(session, "کارشناس جذب")
    assert continued.done and continued.questions_asked == 6


def test_question_cap_drops_conflicting_known_claims(p1_boundary, model):
    session = get_session("conflicting-cap")
    session.questions_asked = 6
    model.append({"target_role": "recruiter", "skills": [
        skill("pivot_tables", "known", "پیوت بلدم"),
        skill("excel", "unknown", "اکسل بلد نیستم"),
        skill("python_basics", "known", "پایتون بلدم"),
    ]})
    result = conv.handle_message(session, "پیوت بلدم؛ اکسل بلد نیستم؛ پایتون بلدم")
    assert result.done and result.questions_asked == 6
    assert result.profile.known_concepts == ["python_basics"]
    assert not conv._conflicts(session.draft)
    assert "ناسازگار" in result.reply


def test_explicit_target_level_required(p1_boundary, model):
    model.append({"target_role":"recruiter", "beginner":True, "knowledge_complete":True})
    result = conv.handle_message(get_session("s"), "می‌خواهم کارشناس جذب شوم؛ مبتدی هستم")
    assert not result.done and "سطح هدف" in result.reply


@pytest.mark.parametrize("status", ["known", "heard", "unknown"])
def test_repeated_correction_is_idempotent(p1_boundary, model, monkeypatch, status):
    seeded_session()
    monkeypatch.setattr(graph, "compute_roadmap", lambda p, tax: Roadmap(
        role=p.target_role, level=p.target_level, nodes=[], edges=[], order=[], summary_fa="خلاصهٔ تست"))
    model.extend([{"skills": [skill("excel", status, "اکسل")]} for _ in range(2)])
    payload = {"session_id": "s", "message": "اکسل"}
    first = client.post("/api/roadmap/correct", json=payload)
    profile = get_session("s").profile.model_dump()
    second = client.post("/api/roadmap/correct", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and get_session("s").profile.model_dump() == profile
    assert "python_basics" in profile["known_concepts"]


def test_unknown_correction_is_not_success(p1_boundary, model):
    session = seeded_session()
    previous = session.profile.model_dump()
    model.append({"skills": [skill("unsupported", "known", "unsupported")]})
    with pytest.raises(P2Error):
        conv.apply_correction(session, "unsupported")
    assert session.profile.model_dump() == previous


def test_quoted_evidence_from_real_model_is_accepted(p1_boundary, model):
    # Real gateway output wraps quotes in «» and may vary spaces/ZWNJ; the claim is still from this turn.
    message = "اکسل را عملاً کار کرده‌ام؛ پایتون را فقط شنیده‌ام."
    model.append(complete(skills=[skill("excel", "known", "«اکسل را عملاً کار کرده‌ام»"),
                                  skill("python_basics", "heard", '"پایتون را فقط  شنیده ام"')]))
    reply = conv.handle_message(get_session("q"), message)
    assert reply.done
    assert reply.profile.known_concepts == ["excel"] and reply.profile.heard_of_only == ["python_basics"]


def test_invented_evidence_is_still_rejected(p1_boundary, model):
    model.append(complete(skills=[skill("excel", "known", "«اکسل را عملاً کار کرده‌ام»")]))
    reply = conv.handle_message(get_session("q2"), "مبتدی هستم")
    assert reply.profile.known_concepts == []


def test_skills_answer_to_knowledge_question_completes(p1_boundary, model):
    # Real gateway sometimes omits knowledge_complete even when the user answered the skills question.
    session = get_session("k")
    model.append({"target_role": "recruiter", "target_level": "mid", "current_level": "junior"})
    first = conv.handle_message(session, "کارشناس جذب جونیور هستم و می‌خوام میانی بشم")
    assert not first.done and "مهارت" in first.reply
    model.append({"skills": [skill("excel", "known", "اکسل را عملاً کار کرده‌ام")]})
    second = conv.handle_message(session, "اکسل را عملاً کار کرده‌ام")
    assert second.done and second.profile.known_concepts == ["excel"]


def test_skills_without_knowledge_question_do_not_complete_early(p1_boundary, model):
    model.append({"target_role": "recruiter", "target_level": "mid", "current_level": "junior",
                  "skills": [skill("excel", "known", "اکسل بلدم")]})
    assert not conv.handle_message(get_session("k2"), "کارشناس جذب جونیور هستم، اکسل بلدم").done


@pytest.mark.parametrize("evidence,ok", [
    ("«پایتون ... را عملاً کار کرده‌ام»", True),   # elided quote, seen on the real gateway
    ("«پایتون… کار کرده‌ام»", True),
    ("«کار کرده‌ام ... پایتون»", False),           # pieces out of order
    ("«پایتون ... جاوا»", False),                  # a piece not in the message
])
def test_elided_quotes(evidence, ok):
    assert conv._quoted(evidence, "پایتون، SQL و گیت را عملاً کار کرده‌ام.") is ok
