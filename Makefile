PY ?= python3
PORT ?= 8000

.PHONY: install install-all api lint

install:            ## core deps (ingest + api)
	$(PY) -m pip install -e ".[dev]"

install-all:        ## everything: vision, sim, llm
	$(PY) -m pip install -e ".[all]"

api:                ## run backend on :$(PORT) (default 8000)
	uvicorn api.main:app --reload --port $(PORT)

lint:
	ruff check .
