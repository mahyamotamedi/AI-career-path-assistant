"""Validated observations; Python controls questions and profile publication."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from app.careers import taxonomy as tax_module
from app.config import settings
from app.jobs.normalize import map_skills
from app.llm import client, prompts
from app.llm.errors import MESSAGES, P2Error
from app.schemas import CareerProfile, ChatResponse, Level
from app.session import SessionState


class _Candidate(CareerProfile):
    _evidence: dict = PrivateAttr(default_factory=dict)


class SkillObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: str
    status: Literal["known", "heard", "unknown"]
    evidence: str = Field(min_length=1, max_length=300)


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_role: str | None = None
    target_level: Level | None = None
    current_level: Level | None = None
    beginner: bool = False
    knowledge_complete: bool = False
    skills: list[SkillObservation] = Field(default_factory=list)


def _context(draft: dict, tax) -> str:
    role = tax.roles.get(draft.get("target_role"))
    ids = set()
    if role:
        for values in role.levels.values():
            ids.update(values)
        # Context only; P1 remains responsible for graph/inference.
        pending = list(ids)
        while pending:
            concept = tax.concepts.get(pending.pop())
            for pre in concept.prerequisites if concept else []:
                if pre not in ids:
                    ids.add(pre)
                    pending.append(pre)
    return json.dumps({
        "roles": {k: {"fa": r.label_fa, "en": r.label_en, "aliases": r.aliases} for k, r in tax.roles.items()},
        "concepts": {k: {"fa": tax.concepts[k].label_fa, "en": tax.concepts[k].label_en,
                          "aliases": tax.concepts[k].aliases} for k in sorted(ids) if k in tax.concepts},
        "draft": draft,
    }, ensure_ascii=False)


def _interpret(session: SessionState, message: str, draft: dict, correction=False) -> Observation:
    tax = tax_module.get_taxonomy()
    res = client.chat_json(session.session_id, [
        {"role": "system", "content": prompts.CORRECTION_SYSTEM if correction else prompts.CAREER_CHAT_SYSTEM},
        {"role": "system", "content": _context(draft, tax)},
        {"role": "user", "content": message},
    ], Observation, model=settings.chat_model)
    if not res.ok:
        raise P2Error(res.error.kind if res.error else "api")
    return res.data


def _merge(draft: dict, obs: Observation, message: str) -> dict:
    tax = tax_module.get_taxonomy()
    result = {**draft, "evidence": dict(draft.get("evidence", {}))}
    if obs.target_role:
        result["target_role"] = tax_module.find_role(obs.target_role, tax)
    for field in ("target_level", "current_level"):
        value = getattr(obs, field)
        if value is not None:
            result[field] = value
    if obs.beginner:
        result["current_level"] = "junior"
    if obs.knowledge_complete:
        result["knowledge_complete"] = True
    for skill in obs.skills:
        # Evidence must be quoted from the current user turn, never an invented rationale.
        if skill.evidence not in message:
            continue
        for cid in map_skills([skill.skill], tax):
            result["evidence"][cid] = {"status": skill.status, "quote": skill.evidence}
    return result


def _conflicts(draft: dict) -> set[str]:
    evidence = draft.get("evidence", {})
    known = [k for k, v in evidence.items() if v["status"] == "known"]
    denied = {k for k, v in evidence.items() if v["status"] != "known"}
    return tax_module.ancestors(tax_module.get_taxonomy().concepts, known) & denied


def _profile(draft: dict) -> CareerProfile:
    evidence = draft.get("evidence", {})
    return CareerProfile(target_role=draft["target_role"], target_level=draft["target_level"],
                         current_level=draft["current_level"],
                         known_concepts=[k for k, v in evidence.items() if v["status"] == "known"],
                         heard_of_only=[k for k, v in evidence.items() if v["status"] == "heard"])


def handle_message(session: SessionState, message: str) -> ChatResponse:
    with session.lock:
        def response(reply, profile=None):
            return ChatResponse(reply=reply, profile=profile, done=profile is not None,
                                questions_asked=session.questions_asked)
        if session.profile:
            return response("پروفایل شما آماده است.", session.profile)
        if not message.strip() or len(message) > 12000:
            return response(MESSAGES["invalid"])
        try:
            candidate = _merge(session.draft, _interpret(session, message, session.draft), message)
            conflicts = _conflicts(candidate)
        except P2Error as exc:
            return response(str(exc))
        question = None
        if not candidate.get("target_role"):
            question = "می‌خواهید برای کدام نقش شغلی برنامه‌ریزی کنیم؟"
        elif not candidate.get("target_level"):
            question = "سطح هدف شما مقدماتی، میانی یا ارشد است؟"
        elif not candidate.get("current_level"):
            question = "سطح فعلی خود را چگونه توصیف می‌کنید؟"
        elif conflicts:
            label = tax_module.get_taxonomy().concepts[sorted(conflicts)[0]].label_fa
            question = f"دربارهٔ {label} اطلاعات ناسازگار است؛ تجربهٔ عملی شما در این مهارت چیست؟"
        elif not candidate.get("knowledge_complete"):
            question = "کدام مهارت‌ها را عملاً انجام داده‌اید و کدام را فقط شنیده‌اید؟"
        if question is None:
            profile = _profile(candidate)
            session.profile = profile
            reply = "پروفایل برنامه‌ریزی آماده است؛ برای فرد مبتدی، junior فقط پایین‌ترین بازهٔ برنامه‌ریزی است."
        elif session.questions_asked < max(0, min(settings.max_questions, 6)):
            session.questions_asked += 1
            profile, reply = None, question
        elif candidate.get("target_role") in tax_module.get_taxonomy().roles:
            assumptions = []
            for field, label in (("target_level", "هدف"), ("current_level", "فعلی")):
                if not candidate.get(field):
                    candidate[field] = "junior"
                    assumptions.append(f"سطح {label} مشخص نبود؛ برای شروع junior (پایین‌ترین بازهٔ برنامه‌ریزی) فرض شد.")
            if conflicts:
                # Best effort must not publish a known closure contradicting explicit evidence.
                # Reassess dependent claims without inventing new unknown-skill statements.
                concepts = tax_module.get_taxonomy().concepts
                evidence = candidate["evidence"]
                denied = {cid for cid, item in evidence.items() if item["status"] != "known"}
                candidate["evidence"] = {
                    cid: item for cid, item in evidence.items()
                    if item["status"] != "known" or not (tax_module.ancestors(concepts, [cid]) & denied)
                }
                assumptions.append("مهارت‌های عملی ناسازگار موقتاً از دانسته‌ها کنار گذاشته شدند.")
            profile = _profile(candidate)
            session.profile = profile
            reply = "برنامهٔ اولیه با اطلاعات موجود و فقط مهارت‌های تأییدشده آماده شد. " + " ".join(assumptions)
        else:
            names = [role.label_fa for _, role in sorted(tax_module.get_taxonomy().roles.items())[:4]]
            profile = None
            reply = "برای ادامه یکی از این نقش‌ها را در پیام بعد نام ببرید: " + "، ".join(names) + "."
        session.draft = candidate
        session.history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": reply}])
        return response(reply, profile)


def apply_correction(session: SessionState, message: str) -> CareerProfile:
    """Return a candidate only. The router commits after real graph computation."""
    with session.lock:
        if session.profile is None or not message.strip() or len(message) > 12000:
            raise P2Error("invalid")
        draft = {**session.profile.model_dump(), "knowledge_complete": True,
                 "evidence": {**{k: {"status": "known", "quote": ""} for k in session.profile.known_concepts},
                              **{k: {"status": "heard", "quote": ""} for k in session.profile.heard_of_only},
                              **session.draft.get("evidence", {})}}
        obs = _interpret(session, message, draft, correction=True)
        if not obs.skills and not any((obs.target_role, obs.target_level, obs.current_level, obs.beginner)):
            raise P2Error("conflict")
        candidate = _merge(draft, obs, message)
        # A repeated explicit observation is a successful no-op, not an ambiguity.
        # Unknown labels or unsupported evidence must still fail safely.
        accepted_skill = any(
            item.evidence in message and map_skills([item.skill], tax_module.get_taxonomy())
            for item in obs.skills
        )
        accepted_field = any((obs.target_level, obs.current_level, obs.beginner)) or (
            obs.target_role is not None and candidate.get("target_role") is not None
        )
        if not (accepted_skill or accepted_field) or not candidate.get("target_role") or _conflicts(candidate):
            raise P2Error("conflict")
        profile = _Candidate(**_profile(candidate).model_dump())
        profile._evidence = candidate["evidence"]
        return profile
