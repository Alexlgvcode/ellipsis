# Lane Watch — Hackathon Checklist

**Team:** **Alex** (detection → events → API) · **Brian** (cameras → simulation → dashboard)
Background: [docs/plan.md](docs/plan.md)

**The checklists live in GitHub Issues, not in this file.** Each feature has one issue with
its checklist: tick boxes right on the issue, with no commit or branch needed. Issues are
grouped into one [milestone per stage](https://github.com/Alexlgvcode/ellipsis/milestones) and assigned to their owner.
- [All open issues](https://github.com/Alexlgvcode/ellipsis/issues)
- [My issues](https://github.com/Alexlgvcode/ellipsis/issues?q=is%3Aopen+assignee%3A%40me)

Work through the stages in order. In each stage, Alex and Brian build their features in
parallel. Each feature has two gates:

- **✅ Automated tests.** Pytest in `tests/`, run by CI on every push to every branch.
- **🧪 User test.** Someone other than the author runs it by hand from a clean `git pull`.

Don't start the next stage's features until your own gates pass.

## Rules

- One branch per feature: `feat/<name>` off `main`. Open a PR when both gates pass, and merge fast.
- Put `Closes #<issue>` in the PR description, so merging closes the feature's issue.
- **CI** (`.github/workflows/ci.yml`) runs `ruff check .` and `pytest` on Python 3.10 and 3.11 for every push and every PR to `main`. `main` only takes merges with green CI.
- Every feature adds `tests/test_<feature>.py`. Run it locally before pushing: `ruff check . && pytest -q`.
- CI installs only the core deps. Tests that need YOLO, SUMO or the Anthropic SDK start with `pytest.importorskip(...)` so they skip in CI; run those locally.
- Unit tests use small files committed under `tests/fixtures/` (a few frames, a tiny mask, a tiny SUMO net), never `data/` (it's gitignored).
- Pull `main` into your branch often (`git pull origin main`).
- `common/schemas.py` is the contract between you. Change it only in its own small PR, and tell the other person first.
- Hand-offs (don't change these):
  - frames at `data/frames/<camera_id>/<YYYYMMDD>/<HHMMSS>.jpg`
  - Event and Recommendation JSON as defined in `common/schemas.py`
- Scope cuts:
  - pretrained YOLO11s, no fine-tuning
  - lane masks on 3–5 cameras
  - no 311 or 511NY
  - 6–10 intersections in SUMO
  - two retiming rules
  - React dashboard (`web/`) that polls the API
  - replay is the demo; live mode is a bonus

> ⚠️ **Start recording frames in Stage 2, while it's daylight.** We have no footage, and the demo needs daytime incidents from today.

## Sequence

| Stage | Alex | Brian | What you can test at the end |
|---|---|---|---|
| 0 | [#1](https://github.com/Alexlgvcode/ellipsis/issues/1) setup + CI (both) | | API runs locally; CI green on `main` |
| 1 | [#2](https://github.com/Alexlgvcode/ellipsis/issues/2) `feat/mock-fixtures` | [#3](https://github.com/Alexlgvcode/ellipsis/issues/3) `feat/camera-list` | Mock data validates; camera list scraped |
| 2 | [#4](https://github.com/Alexlgvcode/ellipsis/issues/4) `feat/api` | [#5](https://github.com/Alexlgvcode/ellipsis/issues/5) `feat/frame-poller` | API serves mocks; frames recording |
| 3 | [#6](https://github.com/Alexlgvcode/ellipsis/issues/6) `feat/detector` | [#7](https://github.com/Alexlgvcode/ellipsis/issues/7) `feat/dashboard` | Boxes on real frames; dashboard on mock data |
| 4 | [#8](https://github.com/Alexlgvcode/ellipsis/issues/8) `feat/tracker` | [#9](https://github.com/Alexlgvcode/ellipsis/issues/9) `feat/sumo-network` | Stationary timers; SUMO runs |
| 5 | [#10](https://github.com/Alexlgvcode/ellipsis/issues/10) `feat/lane-masks` | [#11](https://github.com/Alexlgvcode/ellipsis/issues/11) `feat/sim-scenario` | Masks line up; A/B sim numbers |
| 6 | [#12](https://github.com/Alexlgvcode/ellipsis/issues/12) `feat/event-engine` | [#13](https://github.com/Alexlgvcode/ellipsis/issues/13) `feat/signal-retiming` | Events fire on a clip; mock event → recommendation |
| 7 | [#14](https://github.com/Alexlgvcode/ellipsis/issues/14) `feat/replay` | [#15](https://github.com/Alexlgvcode/ellipsis/issues/15) integration + end-to-end test (both) | **End to end: incident → alert → recommendation → dashboard** |
| 8 | [#16](https://github.com/Alexlgvcode/ellipsis/issues/16) `feat/eval-metrics` | [#17](https://github.com/Alexlgvcode/ellipsis/issues/17) `feat/sim-side-by-side` | Metrics; side-by-side view |
| 9 | [#18](https://github.com/Alexlgvcode/ellipsis/issues/18) `feat/operator-feedback` (both) | | Accept / reject works |
| 10 | [#19](https://github.com/Alexlgvcode/ellipsis/issues/19) `feat/llm-summary` | [#20](https://github.com/Alexlgvcode/ellipsis/issues/20) `feat/live-mode` | Bonus features |
| 11 | [#21](https://github.com/Alexlgvcode/ellipsis/issues/21) demo and submit (both) | | Full rehearsal |
