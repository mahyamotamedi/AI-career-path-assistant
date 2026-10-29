from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.jobs import resume_parser
from app.llm.errors import P2Error
from app.schemas import ResumeProfile
from app.session import get_session

router = APIRouter()


@router.post("/resume", response_model=ResumeProfile)
async def upload_resume(session_id: str = Form(...), file: UploadFile = File(...)) -> ResumeProfile:
    try:
        name = file.filename or ""
        if not name.lower().endswith((".pdf", ".docx")):
            raise HTTPException(400, "فقط فایل PDF یا DOCX پذیرفته می‌شود")
        limit = settings.max_upload_mb * 1024 * 1024
        data = bytearray()
        while len(data) <= limit:
            chunk = await file.read(min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, "فایل خیلی بزرگ است")

        def real() -> ResumeProfile:
            session = get_session(session_id)
            with session.lock:
                text = resume_parser.extract_text(name, bytes(data))
                profile = resume_parser.parse_resume(session_id, text)
                session.resume = profile
                return profile
        try:
            return await run_in_threadpool(real)
        except P2Error as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
    finally:
        await file.close()
