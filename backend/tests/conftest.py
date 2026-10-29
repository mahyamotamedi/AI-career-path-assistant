"""Network-free session and configuration isolation."""
import pytest
from app.session import _sessions
from app.config import settings


@pytest.fixture(autouse=True)
def isolated_sessions(monkeypatch):
    _sessions.clear()
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "chat_model", "")
    monkeypatch.setattr(settings, "extract_model", "")
    monkeypatch.setattr(settings, "embed_model", "")
    monkeypatch.setattr(settings, "price_table", {})
    monkeypatch.setattr(settings, "max_questions", 6)
    monkeypatch.setattr(settings, "max_upload_mb", 5)
    monkeypatch.setattr(settings, "llm_json_budget_s", 8.0)
    monkeypatch.setattr(settings, "llm_json_mode", True)
    monkeypatch.setattr(settings, "llm_send_temperature", False)
    yield
    _sessions.clear()


from app.careers import taxonomy as tax_module
from app.careers.taxonomy import Concept, Role, Taxonomy


@pytest.fixture
def p1_boundary(monkeypatch):
    tax = Taxonomy(concepts={
        "excel": Concept(id="excel", label_fa="اکسل", label_en="Excel"),
        "pivot_tables": Concept(id="pivot_tables", label_fa="جدول محوری", label_en="Pivot tables", prerequisites=["excel"]),
        "python_basics": Concept(id="python_basics", label_fa="پایتون", label_en="Python"),
    }, roles={"recruiter": Role(id="recruiter", label_fa="کارشناس جذب", label_en="Recruiter", domain="business", levels={"junior": ["excel"]})})
    monkeypatch.setattr(tax_module, "get_taxonomy", lambda: tax)
    monkeypatch.setattr(tax_module, "find_role", lambda value, tax: value if value in tax.roles else None, raising=False)
    # A fixed contract fixture, not a replacement production graph/closure implementation.
    monkeypatch.setattr(tax_module, "ancestors", lambda concepts, ids: set(ids) | ({"excel"} if "pivot_tables" in ids else set()), raising=False)
    return tax
