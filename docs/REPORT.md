# Technical Report (1–2 pages)

## Architecture
_Short description + diagram reference (see ARCHITECTURE.md)._

## Models & why
| Task | Model | Why |
|---|---|---|
| Chat | | |
| Extraction | | |
| Embeddings | | |

## Taxonomy design
_Roles, domains, concepts, prerequisite edges, how levels work, how resources were verified._

## Data collection (Module B, P3)
80 real postings (40 each) from **jobinja.ir** (server-rendered HTML + JSON-LD; keyword listings, then detail pages) and **jobvision.ir** (public JSON list endpoint `JobPost/List` called with a POST body, plus the server-rendered detail page). Keywords span software, data, business and marketing so the sample covers the taxonomy domains. Collection is polite: robots.txt is checked before every request with a wildcard-aware matcher (jobvision blocks any URL containing `?`; its API host allows only `JobPost/List`), at least 3 s between requests per host, an identifying User-Agent, a disk cache, no logins or cookies, and the API's disallowed detail endpoint is never called. Postings are normalised to one schema (title, company, canonical city, remote, seniority from title keywords then years, requirement lines, `skill_ids`), then deduplicated (same URL, or same company and city with a normalised/fuzzy title match). Skill mapping uses taxonomy labels and aliases only (no LLM): 78 of 80 postings have at least one mapped skill.

## Ranking method
**Baseline:** BM25 (`rank_bm25`) over posting title + requirements; the query is the resume's skills, previous roles and the Persian/English labels of its mapped skills. **Hybrid (ours):** `score = (w_skill·skill_score + w_embed·embed_score + w_seniority·seniority_fit) / Σw`, with the default weights 0.6 / 0.4 / 0.1 (renormalised over the signals that are available). `skill_score` is coverage of the posting's mapped skills blended with Jaccard (0.8/0.2); `embed_score` is the cosine between the resume and posting embeddings (posting vectors cached on disk by id + text hash; the resume vector is never stored); `seniority_fit` is 1 / 0.5 / 0 for same / one step or unknown / two steps. If the embedding service fails or is not configured, the embedding term is dropped and ranking continues on the other signals (no error). Ties are broken by posting id, so results are deterministic. Matched/missing skills are set operations on `skill_ids`, and the Persian explanation is a deterministic template (no LLM).

## Evaluation results
3 synthetic resumes (junior data analyst, mid Python backend, junior digital marketing) x 80 postings, full snapshot ranked without filters; `make eval` reproduces the table. Labels are rule-based on posting **title and seniority only** (same role family and the resume's level or one step away, or unknown level), so they do not depend on any ranker's scores, skills or embeddings; they were spot-checked, not fully human-reviewed. Weights are the config defaults and were **not tuned** on these resumes.

| Method | P@5 | nDCG@10 |
|---|---|---|
| BM25 baseline | 1.000 | 0.890 |
| Hybrid (ours) [no embeddings: skills+seniority] | 0.600 | 0.580 |
| Skills only (ablation) | 0.600 | 0.559 |

3 synthetic resumes x 80 labelled postings; embeddings NOT available (no gateway key): hybrid = skill overlap + seniority fit only.

Per resume (P@5 / nDCG@10):

| Resume | #relevant | BM25 baseline | Hybrid (ours) [no embeddings: skills+seniority] | Skills only (ablation) |
|---|---|---|---|---|
| r1_data_analyst_junior | 8 | 1.00 / 0.82 | 0.60 / 0.50 | 0.60 / 0.49 |
| r2_backend_python_mid | 9 | 1.00 / 0.85 | 0.20 / 0.37 | 0.20 / 0.33 |
| r3_digital_marketing_junior | 16 | 1.00 / 1.00 | 1.00 / 0.86 | 1.00 / 0.86 |

**Reading the result.** In this run embeddings were not available (no gateway key), so "Hybrid" is skill overlap + seniority fit, and it did **not** beat BM25 (BM25 P@5 1.00 vs 0.60). Two causes are visible in the top-5 lists: postings with only two or three mapped skills get full coverage and outrank real analyst/Python postings (Data Engineer / Data Scientist above Data Analyst), and the title-based labels favour BM25, which also matches titles. The embedding term, which compares the whole resume with the whole posting text, is the part meant to fix this; the table must be re-run with embeddings before drawing conclusions about the hybrid method.

## Cost per session
_Average tokens and estimated USD for a typical session of each module._

**Module B latency (P3):** ranking all 80 postings takes ~10 ms for BM25 and, with embeddings, ~10 ms of local compute plus gateway calls: one-time embedding of the 80 posting texts (2 batched calls, then cached on disk) and one call for the resume per request. Measured here with a fake gateway only (cold 0.008 s, warm 0.007 s); real gateway latency was not measured because no key was available — expected well under the 60 s limit (NF-02). A hidden-resume check (junior React developer, not an eval role; DOCX through `/api/resume` with the LLM answer stubbed) returned React/front-end postings first for both methods.

## AI-assistant disclosure
_Which AI coding assistants were used and for what._

## Limitations
_Small taxonomy, LLM errors, language coverage, etc._ **P3 (jobs & ranking):** the 80 postings are Tehran-heavy with only 5 remote jobs and come from two sites; skill coverage depends on taxonomy aliases (generic or unlisted skills such as Google Search Console are not mapped, and a posting with few mapped skills can outrank richer ones); the evaluation set is small (3 resumes) with rule-based labels that were only spot-checked; hybrid numbers need an embeddings run; postings are a snapshot from 29 October 2026 (incremental refresh every 5 h is designed — TTL listing cache, upsert, expiry — but not deployed).

## P2 implementation status (29 October 2026)

Codex assisted with the synchronous LLM wrapper, typed Persian interview/corrections,
resume extraction, dynamic skill matching, router error handling, and mocked tests.
Public schemas/frontend types, taxonomy/graph/resources, ranking, and deployment remain
unchanged. Shared supporting changes are confined to session locks/draft metadata,
configuration, resume/correction/usage routers, `.env.example`, tests, and existing docs.
No dependency versions were changed.

The current `p2-llm-layer` checkout is based on `fc59118`, containing merged P1 `28ddedf`
through `9aa3b8d`. The earlier missing-P1-branch blocker is resolved. P1's actual
`find_role`, `ancestors`, graph engine, and Persian summary are reused unchanged.
The new implementation plan was reconciled with these concrete interfaces; see
`docs/superpowers/plans/2026-10-29-career-path-assistant.md`. P2 corrections now accept
repeated positive/heard/negative observations as idempotent. Real-P1 integration tests
cover current aliases, chat → graph, repeated correction, summary preservation, and
prerequisite-conflict rollback; they still need runtime verification. P3 ranking/collection
remain unfinished; fixture job matches are development placeholders.

The shell has Python 3.13.5, not the Docker Python 3.11 or Makefile's default Python 3.12.
A local `backend/.venv` was created. Network dependency installation failed, and the local
wheel cache lacks pydantic-settings, PyMuPDF, python-docx, and networkx. Runtime test
results and taxonomy validation are not established until those dependencies are present.
`make test` is also blocked by missing Xcode command-line tools on this host.
No real gateway validation, measured latency/cost, external URL checks, or full end-to-end
readiness is claimed. The mock suite does not establish complete 154-concept coverage.

Verification attempted on this host:

| Command (repository root unless stated) | Actual result |
|---|---|
| `python3 -m compileall -q backend/app backend/tests` | Passed (syntax only) |
| `git diff --check` | Passed |
| `make test` | Could not start: Xcode command-line tools unavailable |
| `cd backend && .venv/bin/python -m pytest -q tests/test_llm.py tests/test_normalize.py tests/test_conversation.py tests/test_resume.py tests/test_p2_p1_integration.py` | Setup import error: missing `pydantic_settings`; 0 tests executed |
| `cd backend && .venv/bin/python -m pytest -q` | Same setup import error; 0 tests executed; pass/fail/xfail counts unavailable |
| `cd backend && .venv/bin/python -m scripts.validate_taxonomy` | Import error: missing `pydantic_settings`; no taxonomy result |
| `cd backend && .venv/bin/python -c 'from app.main import app; print(app.title)'` | Same missing dependency |

Cached packages supplied part of the isolated environment, but did not satisfy all required
imports. No Python 3.11/3.12 runtime was available for compatibility verification.

Opt-in live check requires `LLM_BASE_URL` (organiser gateway), `LLM_API_KEY`, `CHAT_MODEL`,
`EXTRACT_MODEL`, and `EMBED_MODEL` for embedding checks only. Set `PRICE_TABLE` to JSON
mapping exact model IDs to `[input_usd_per_million, output_usd_per_million]`, with an honest
`PRICE_BASIS`. Review `LLM_JSON_MODE`, `LLM_SEND_TEMPERATURE`, `LLM_TIMEOUT_S`, and
`LLM_JSON_BUDGET_S` against that gateway's supported parameters. Never put keys in tests.

Synthetic Persian demo with merged P1: «هدفم تحلیلگر داده در سطح junior است؛ مبتدی‌ام.
اکسل را عملاً کار کرده‌ام؛ SQL را فقط شنیده‌ام و مهارت عملی دیگری ندارم.» Expected IDs:
`target_role=data_analyst`, `target_level=junior`, `current_level=junior`,
`known_concepts=[excel]`, `heard_of_only=[sql_basics]`. Then send «من اکسل بلد نیستم» to
`/api/roadmap/correct`: Excel must become todo; if another known skill implies it, a
conflict must be explained instead of reporting success. A synthetic text resume can say
«سابقهٔ کار: صفر سال؛ مهارت‌ها: Python و Excel» and map to `python_basics` and `excel`.
