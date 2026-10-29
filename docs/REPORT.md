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

## Ranking method
_Baseline BM25 vs hybrid (skill overlap + embeddings + optional LLM re-rank), weights, explanations._

## Evaluation results
3 synthetic resumes × ≥20 labelled postings.

| Method | P@5 | nDCG@10 |
|---|---|---|
| BM25 baseline | | |
| Ours (hybrid) | | |

## Cost per session
_Average tokens and estimated USD for a typical session of each module._

## AI-assistant disclosure
_Which AI coding assistants were used and for what._

## Limitations
_Small taxonomy, posting coverage/freshness, LLM errors, language coverage, etc._

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
