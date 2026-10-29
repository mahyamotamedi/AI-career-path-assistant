from fastapi import APIRouter

from app.schemas import UsageReport
from app.session import get_session

router = APIRouter()


@router.get("/usage/{session_id}", response_model=UsageReport)
def usage(session_id: str) -> UsageReport:
    session = get_session(session_id)
    with session.usage_lock:
        report = session.usage.model_copy()
        report.est_cost_usd = round(report.est_cost_usd, 10)
        return report
