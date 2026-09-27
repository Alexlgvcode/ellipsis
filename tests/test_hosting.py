"""Running the API and pipeline on a server left on (deploy/): CORS, daily caps, frame pruning."""

import os
from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.main import create_app
from common.config import Settings
from common.quota import DailyCap
from scripts.live import prune_frames
from signals.worker import capped

SITE = "https://ellipsisnyc.tech"


def make(tmp_path, **env) -> TestClient:
    return TestClient(create_app(Settings(LW_DATABASE_URL=f"sqlite:///{tmp_path / 'api.db'}",
                                          LW_MOCK_MODE=False, **env)))


def test_the_hosted_site_may_read_the_api_but_not_write(tmp_path):
    with make(tmp_path, LW_CORS_ORIGINS=f"{SITE}, http://localhost:5173") as c:
        resp = c.get("/health", headers={"origin": SITE})
        assert resp.headers["access-control-allow-origin"] == SITE
        pre = c.options("/events", headers={"origin": SITE,
                                            "access-control-request-method": "POST"})
        assert pre.status_code == 400  # no cross-site writes
        other = c.get("/health", headers={"origin": "https://elsewhere.example"})
        assert "access-control-allow-origin" not in other.headers


def test_without_origins_there_are_no_cors_headers(tmp_path):
    with make(tmp_path) as c:
        resp = c.get("/health", headers={"origin": SITE})
        assert "access-control-allow-origin" not in resp.headers


def test_daily_cap_resets_each_day_and_zero_means_no_limit():
    day = [date(2026, 9, 27)]
    cap = DailyCap(2, today=lambda: day[0])
    assert [cap.take() for _ in range(3)] == [True, True, False]
    day[0] = date(2026, 9, 28)
    assert cap.take()
    assert all(DailyCap(0).take() for _ in range(100))


def test_notes_stop_at_the_cap_and_the_rest_go_without():
    calls = []
    note = capped(lambda _c, event, _r, _n: calls.append(event.id) or "ok", DailyCap(1))
    assert note(None, SimpleNamespace(id="evt_1"), None, None) == "ok"
    assert note(None, SimpleNamespace(id="evt_2"), None, None) is None
    assert calls == ["evt_1"]


def test_prune_frames_deletes_old_frames_and_empty_days(tmp_path):
    old = tmp_path / "cam" / "20260926" / "120000.jpg"
    new = tmp_path / "cam" / "20260927" / "120000.jpg"
    for p in (old, new):
        p.parent.mkdir(parents=True)
        p.write_bytes(b"x")
    os.utime(old, (1000, 1000))
    os.utime(new, (5000, 5000))
    assert prune_frames(tmp_path, keep_s=600, now=5100) == 1
    assert not old.parent.exists() and new.exists()
