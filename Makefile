PY ?= python3.12
VENV = backend/.venv
BIN = $(VENV)/bin

.PHONY: install dev dev-backend dev-frontend test collect refresh eval

install:
	test -d $(VENV) || $(PY) -m venv $(VENV)
	$(BIN)/pip install -r backend/requirements.txt
	cd frontend && npm install

dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/python -m pytest -q

collect:
	cd backend && .venv/bin/python -m scripts.collect_jobs

refresh:
	cd backend && .venv/bin/python -m scripts.collect_jobs --incremental

eval:
	cd backend && .venv/bin/python -m scripts.evaluate_ranking
