"""Bounded document extraction and validated model extraction; no content persistence."""
import io
import json
import zipfile

from pydantic import BaseModel, ConfigDict, Field

from app.careers.taxonomy import get_taxonomy
from app.config import settings
from app.jobs.normalize import map_skills, normalize_text
from app.llm import client, prompts
from app.llm.errors import P2Error
from app.schemas import Level, ResumeProfile

MAX_TEXT = 100_000


class ResumeExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skills: list[str] = Field(default_factory=list)
    years_experience: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    education: list[str] = Field(default_factory=list)
    previous_roles: list[str] = Field(default_factory=list)
    location: str | None = None
    level_guess: Level | None = None


def extract_text(filename: str, data: bytes) -> str:
    if not data or len(data) > settings.max_upload_mb * 1024 * 1024:
        raise P2Error("document")
    name = filename.lower()
    if not name.endswith((".pdf", ".docx")):
        raise P2Error("invalid")
    try:
        if name.endswith(".pdf"):
            import fitz
            with fitz.open(stream=data, filetype="pdf") as doc:
                if doc.needs_pass or len(doc) > 200:
                    raise P2Error("document")
                chunks = []
                length = 0
                for page in doc:
                    chunk = page.get_text(sort=True)
                    length += len(chunk)
                    if length > MAX_TEXT:
                        raise P2Error("document")
                    chunks.append(chunk)
                text = "\n\n".join(chunks)
        else:
            import docx
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 20 * 1024 * 1024:
                    raise P2Error("document")
            doc = docx.Document(io.BytesIO(data))
            chunks = []
            for element in doc.element.body.iterchildren():
                if element.tag == qn("w:p"):
                    chunks.append(Paragraph(element, doc).text)
                elif element.tag == qn("w:tbl"):
                    chunks.extend("\t".join(c.text for c in row.cells) for row in Table(element, doc).rows)
            text = "\n".join(chunks)
    except P2Error:
        raise
    except Exception:
        # Document libraries have heterogeneous parse errors; never expose their messages.
        raise P2Error("document") from None
    if not text.strip() or len(text) > MAX_TEXT:
        raise P2Error("document")
    return text


def parse_resume(session_id: str, text: str) -> ResumeProfile:
    if not text.strip() or len(text) > MAX_TEXT:
        raise P2Error("document")
    res = client.chat_json(session_id, [
        {"role": "system", "content": prompts.RESUME_EXTRACT_SYSTEM},
        {"role": "user", "content": json.dumps({"untrusted_resume": normalize_text(text)}, ensure_ascii=False)},
    ], ResumeExtraction, model=settings.extract_model)
    if not res.ok:
        raise P2Error(res.error.kind if res.error else "api")
    extraction = res.data
    # The public contract uses zero when no years are stated; do not infer level from it.
    values = extraction.model_dump()
    if values["years_experience"] is None:
        values["years_experience"] = 0
    return ResumeProfile(**values, skill_ids=map_skills(extraction.skills, get_taxonomy()))
