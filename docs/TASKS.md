# Tasks — 4 workstreams

Stubs raise `NotImplementedError`; routers serve fixtures meanwhile. Requirement IDs/priorities follow the RFP reconciliation in `docs/superpowers/plans/2026-10-29-career-path-assistant.md`. Checkboxes require verification, not just implementation.

## P1 — Taxonomy & Graph · owner: _TBD_
Folders: `backend/app/careers/{taxonomy,graph,resources}.py`, `backend/data/taxonomy/`, `backend/scripts/{validate,verify}_*.py`, `backend/tests/test_graph.py`
- [ ] A-02 [Must] Taxonomy: ≥10 roles, ≥3 domains (software, data, business), junior/mid/senior concept sets
- [ ] A-03 [Must] Prerequisite edges + `check_acyclic`
- [ ] A-05 [Must] `compute_roadmap` (targets + prerequisites − known, topological order, layers)
- [ ] A-07 [Must] Resources with `verified` flags; `verify_resources.py` writes results back
- [ ] A-04 [Must] Unknown IDs dropped; `heard_of_only` never directly counts as known
- [ ] A-09 [Should] Persian summary generated from the real graph

Done when: `make test` has no xfail left in `test_graph.py`; `python -m scripts.validate_taxonomy` is clean; every concept has ≥1 verified resource.

## P2 — LLM Layer · owner: _TBD_
Folders: `backend/app/llm/`, `backend/app/careers/conversation.py`, `backend/app/jobs/resume_parser.py`, `backend/app/jobs/normalize.py`
- [ ] A-01 [Must] Persian chat, ≤6 questions
- [ ] A-04 [Must] JSON profile validated against taxonomy
- [ ] A-08 [Should] Correction handling (transactional and idempotent): "من اکسل بلد نیستم"
- [ ] B-01 [Must] PDF/DOCX text extraction, Persian + English
- [ ] B-02 [Must] Resume → `ResumeProfile`, `map_skills`
- [ ] NF-06 [Must] Graceful LLM errors/timeouts/malformed JSON
- [ ] NF-05 [Should] Token + cost tracking per session
- [ ] A-10 [Could] Voice STT + TTS (optional)

Done when: the full chat → profile → roadmap flow runs on the real LLM; a bad-JSON/timeout test shows a friendly Persian message; `/api/usage` shows real numbers.

## P3 — Jobs & Ranking · owner: _TBD_
Folders: `backend/app/jobs/{collector,dedup,store,ranking,explain}.py`, `backend/scripts/{collect_jobs,evaluate_ranking}.py`, `backend/data/{jobs,eval}/`
- [ ] B-03 [Must] ≥50 postings from ≥2 public sources, normalised schema (cached by **11:00**)
- [ ] B-09 [Should] Dedup across sources
- [ ] B-04 [Must] Top 10 with scores
- [ ] B-07 [Should] `baseline_rank` + `hybrid_rank`, measured beyond-keyword ranking
- [ ] B-05 [Must] Matched/missing skills + deterministic Persian explanation
- [ ] B-06 [Must] Link to original posting
- [ ] B-08 [Should] Filters (location, seniority, remote) verified
- [ ] NF-08 [Must] Scraper: robots.txt, ≥2 s/host, User-Agent
- [ ] §10.2 [Must] Eval: 3 synthetic resumes × ≥20 labelled postings; P@5 and nDCG@10 vs BM25

Done when: `make collect` yields ≥50 deduped postings; `make eval` prints the results table for both methods.

## P4 — Frontend & Integration · owner: _TBD_
Folders: `frontend/`, `docker-compose.yml`, `Makefile`, `README.md`, `docs/REPORT.md`
- [ ] A-06 [Must] Roadmap graph polish (layers, resources, known/todo)
- [ ] B-06 [Must] Job cards with score, matched/missing, link
- [ ] B-08 [Should] Filters UI
- [ ] NF-01 [Must] RTL, Persian UI, Vazirmatn
- [ ] NF-03 [Must] Privacy notice before upload (done in skeleton; verify wording)
- [ ] NF-05 [Should] Usage/cost display
- [ ] NF-07 [Should] Single-command start
- [ ] NF-06 [Must] Safe Persian errors and empty states
- [ ] B-10 [Could] "Roadmap for this job's missing skills" (calls Module A)
- [ ] A-11 [Could] Export roadmap as image/PDF
- [ ] Slides and demo script

Done when: all three demo scenarios run end-to-end from `docker compose up` with no console errors.

## Timeline

| Time | Milestone |
|---|---|
| 09:45 | Contracts frozen, skeleton runs |
| 11:00 | Postings cached |
| 13:00 | End-to-end with real components |
| 15:30 | Feature freeze |
| 16:00 | Eval numbers + report |
| 16:30 | Code freeze |

## Demo script checklist

- [ ] **1. Beginner → junior data analyst:** chat, roadmap graph, resources, correction "من اکسل بلد نیستم" regenerates it
- [ ] **2. Junior backend → senior:** roadmap shows only missing concepts, prerequisites ordered
- [ ] **3. Graduate uploads resume:** privacy notice, upload, top-10 with matched/missing, filters, link to original posting
- [ ] Show eval table (baseline vs ours) and cost per session
- [ ] Show an LLM failure handled gracefully (e.g. kill the key)

## P2 handoff

Implementation lives on `p2-llm-layer`, now based on `fc59118` with P1 `28ddedf`
already merged. P2 error paths no longer raise `NotImplementedError`. The shared session,
configuration, resume/correction/usage router changes preserve the public contracts.
Use `handle_message(session, message)`, `apply_correction(session, message)` (candidate),
`chat_json(session_id, messages, schema)`, and `map_skills(skills, taxonomy)`; see the
reconciled plan for full signatures. Repeated accepted corrections are idempotent;
prerequisite conflicts remain explicit and do not commit state. Keep P1 graph tests unchanged.

Read ARCHITECTURE.md for frozen experience/level and accounting limitations. The real-P1
integration tests exist but are not verified: runtime setup is blocked by missing dependencies.
Run `cd backend && .venv/bin/python -m pytest -q` and
`cd backend && .venv/bin/python -m scripts.validate_taxonomy` once dependencies are installed.
P3 ranking remains a separate workstream. No live gateway test or latency claim has been made.
