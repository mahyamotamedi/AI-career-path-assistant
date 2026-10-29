VENV = backend/.venv
ifeq ($(OS),Windows_NT)
PY ?= python
VBIN = .venv/Scripts
else
PY ?= python3.12
VBIN = .venv/bin
endif
BIN = backend/$(VBIN)

.PHONY: install dev dev-backend dev-frontend test collect refresh eval

install:
	$(if $(wildcard $(VENV)),,$(PY) -m venv $(VENV))
	$(BIN)/python -m pip install -r backend/requirements.txt
	cd frontend && npm install

dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && $(VBIN)/python -m uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && $(VBIN)/python -m pytest -q

collect:
	cd backend && $(VBIN)/python -m scripts.collect_jobs

refresh:
	cd backend && $(VBIN)/python -m scripts.collect_jobs --incremental

eval:
	cd backend && $(VBIN)/python -m scripts.evaluate_ranking
