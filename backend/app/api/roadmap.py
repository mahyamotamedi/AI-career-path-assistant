from fastapi import APIRouter, HTTPException

from app.careers import conversation, graph
from app.careers.taxonomy import get_taxonomy
from app.llm.errors import P2Error
from app.schemas import CareerProfile, CorrectionRequest, Roadmap
from app.session import get_session
from app.stubs import load_fixture, run_or_stub

router = APIRouter()


def _stub_roadmap() -> Roadmap:
    return Roadmap(**load_fixture("roadmap.json"))


@router.post("/roadmap", response_model=Roadmap)
def make_roadmap(profile: CareerProfile) -> Roadmap:
    try:
        return run_or_stub(lambda: graph.compute_roadmap(profile, get_taxonomy()), _stub_roadmap)
    except ValueError:
        raise HTTPException(422, "برای این نقش شغلی نقشهٔ راه در دسترس نیست.") from None


@router.post("/roadmap/correct", response_model=Roadmap)
def correct_roadmap(req: CorrectionRequest) -> Roadmap:
    session = get_session(req.session_id)

    def real() -> Roadmap:
        with session.lock:
            previous = session.profile
            draft = session.draft
            try:
                candidate = conversation.apply_correction(session, req.message)
                result = Roadmap.model_validate(graph.compute_roadmap(candidate, get_taxonomy()))
            except Exception:
                session.profile, session.draft = previous, draft
                raise
            session.profile = CareerProfile.model_validate(candidate.model_dump())
            session.draft = {**candidate.model_dump(), "knowledge_complete": True,
                             "evidence": getattr(candidate, "_evidence", {})}
            return result

    try:
        return run_or_stub(real, _stub_roadmap)
    except P2Error as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except (ValueError, RuntimeError):
        raise HTTPException(422, "بازسازی نقشه ممکن نشد؛ پروفایل قبلی حفظ شد.") from None
