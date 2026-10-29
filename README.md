# AI Career Path Assistant — دستیار مسیر شغلی با هوش مصنوعی

Persian-first (RTL) web app for the Rahnama College ML Bootcamp hackathon (RFP RC-MLB-HACK-2026-01).
**Module A** turns a short Persian chat into a deterministic, prerequisite-ordered learning roadmap.
**Module B** parses an uploaded resume (PDF/DOCX) and ranks cached real job postings with matched/missing skills.
The LLM only extracts and converses; roadmap and scoring logic are plain code.

## Quick start

```bash
cp .env.example .env     # fill LLM_BASE_URL, LLM_API_KEY, model names
docker compose up        # backend :8000, frontend :5173
```

Without Docker: `make install && make dev`. Other targets: `make test`, `make collect`, `make eval`.
Until the real components exist, every endpoint falls back to `backend/data/fixtures/` (look for `STUB` in the logs).

## Endpoints (`/api`)

`POST /chat` · `POST /roadmap` · `POST /roadmap/correct` · `POST /resume` (multipart) · `POST /jobs/match` · `GET /jobs/count` · `GET /usage/{session_id}` · `GET /health`

Interactive docs: http://localhost:8000/docs

## Models used

| Purpose | Model |
|---|---|
| Chat | _TBD (CHAT_MODEL)_ |
| Extraction | _TBD (EXTRACT_MODEL)_ |
| Embeddings | _TBD (EMBED_MODEL)_ |

## Data sources

| Source | Method | robots.txt | Postings | Collected |
|---|---|---|---|---|
| jobinja.ir | Server-rendered HTML (keyword listings + detail pages, JSON-LD) | Allows everything except `/style_guide/` | 40 | 2026-10-29 |
| jobvision.ir | `POST candidateapi.jobvision.ir/api/v1/JobPost/List` (JSON body, no query string) + server-rendered `jobvision.ir/jobs/<id>` pages | API host allows only `/api/v1/JobPost/List`; main site blocks URLs with `?` (we use none) | 40 | 2026-10-29 |

Total after dedup: 80 (`backend/data/jobs/postings.jsonl`). Requests use the `RahnamaHackathonBot` User-Agent, ≥3 s per host, robots.txt checked before every request (Google-style wildcard matching in `collector/base.py`). No logins or cookies.

## Acknowledgements

FastAPI, Pydantic, openai SDK, networkx, PyYAML, PyMuPDF, python-docx, hazm, httpx, rank_bm25, numpy, scikit-learn, pytest, React, Vite, React Flow (@xyflow/react), Vazirmatn font.

AI coding assistants (Claude Code) were used to build this project.
