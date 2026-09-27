PY ?= python3
PORT ?= 8000

.PHONY: install install-all api web-install web web-test lint sim-network sim-routes sim-validate sim-gui sim-scenario sim-retime recommend-worker

install:            ## core deps (ingest + api)
	$(PY) -m pip install -e ".[dev]"

install-all:        ## everything: vision, sim, llm
	$(PY) -m pip install -e ".[all]"

api:                ## run backend on :$(PORT) (default 8000)
	uvicorn api.main:app --reload --port $(PORT)

web-install:        ## dashboard deps (Node 20+)
	cd web && npm ci

web:                ## ellipsis dashboard on :5173 (proxies /api to LW_API_URL)
	cd web && npm run dev

web-test:           ## dashboard unit + app tests, typecheck
	cd web && npm test && npm run typecheck

lint:
	ruff check .

sim-network:        ## OSM -> midtown.net.xml (reuses the extract if present)
	$(PY) -m sim.network.build --skip-osm

sim-routes:         ## corridor flows + randomTrips -> midtown.rou.xml
	$(PY) -m sim.routes.build_routes

sim-validate:       ## structure + 15 min headless run
	$(PY) -m sim.network.validate

sim-gui:            ## open the Midtown net in sumo-gui
	sumo-gui -c sim/network/midtown.sumocfg

sim-scenario:       ## 8th Ave blockage: plan A vs empty, then A vs B
	$(PY) -m sim.run_scenario --demo

sim-retime:         ## mock events -> real sim numbers, POST if the API is up
	$(PY) -m signals.retime --post

recommend-worker:   ## score new API events (run with LW_MOCK_MODE=false)
	$(PY) -m signals.worker
