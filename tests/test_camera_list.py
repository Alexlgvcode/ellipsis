"""Camera list scraping and name/coordinate resolution. No network: httpx is mocked."""

import json
from pathlib import Path

import httpx
import pytest

from common.config import AREAS
from common.schemas import Camera
from ingest import camera_list as cl

FIXTURE = Path(__file__).parent / "fixtures" / "cameras_sample.json"
URL = "https://cams.test/api/cameras/"
PENN = AREAS["penn"]


@pytest.fixture
def raw() -> list[dict]:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def serve(payload, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, (bytes, str)):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)
    return handler


def cam(id_, name, lat, lon, online=True) -> Camera:
    return Camera(id=id_, name=name, lat=lat, lon=lon, image_url=f"https://x/{id_}/image",
                  is_online=online)


# --- parsing -------------------------------------------------------------------------


def test_parse_maps_raw_fields(raw):
    c = cl.parse_camera(raw[2])
    assert c.id == "ec9ffb62-e3bf-4352-8bcf-7c9adf5fbe9c"
    assert c.name == "8th Ave @ 31st St"
    assert (c.lat, c.lon) == (40.750297, -73.99483)
    assert c.area == "Manhattan"
    assert c.image_url.endswith("/ec9ffb62-e3bf-4352-8bcf-7c9adf5fbe9c/image")
    assert c.is_online is True


@pytest.mark.parametrize("value, expected", [("true", True), ("false", False),
                                             (True, True), (False, False), ("TRUE", True)])
def test_is_online_accepts_strings_and_bools(raw, value, expected):
    assert cl.parse_camera({**raw[0], "isOnline": value}).is_online is expected


def test_malformed_rows_are_skipped(raw):
    cams = cl.parse_cameras(raw)
    assert len(cams) == len(raw) - 1
    assert "broken-row-no-coords" not in {c.id for c in cams}


def test_fetch_raw_uses_mock_transport(raw):
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, json=raw)

    with client_for(handler) as c:
        assert cl.fetch_raw(c, URL) == raw
    assert seen["ua"].startswith("LaneWatch")


@pytest.mark.parametrize("handler", [serve({}, 500), serve(b"<html>down</html>"),
                                     serve({"not": "a list"})])
def test_fetch_raw_raises_after_retries(handler):
    calls = []

    def counting(request):
        calls.append(1)
        return handler(request)

    with client_for(counting) as c, pytest.raises(cl.CameraListError):
        cl.fetch_raw(c, URL, retries=3)
    assert len(calls) == 3


def test_fetch_raw_recovers_on_retry(raw):
    responses = iter([httpx.Response(503), httpx.Response(200, json=raw)])
    with client_for(lambda r: next(responses)) as c:
        assert cl.fetch_raw(c, URL) == raw


# --- area filter ---------------------------------------------------------------------


def test_area_filter_keeps_penn_drops_rest(raw):
    kept = {c.name for c in cl.filter_to_area(cl.parse_cameras(raw), PENN)}
    assert kept == {"8th Ave @ 31st St", "Broadway @ 6 Ave / 33 St", "7 Ave @ 34 St",
                    "8 Ave @ 34 St"}


def test_area_filter_includes_edges():
    min_lat, min_lon, max_lat, max_lon = PENN
    corners = [cam("a", "a", min_lat, min_lon), cam("b", "b", max_lat, max_lon),
               cam("c", "c", max_lat + 1e-6, max_lon)]
    assert [c.id for c in cl.filter_to_area(corners, PENN)] == ["a", "b"]


# --- name matching -------------------------------------------------------------------


@pytest.mark.parametrize("a, b", [
    ("8th Ave @ 31st St", "8 Ave @ 31 St"),
    ("8 Avenue & 34 Street", "8 Ave @ 34 St"),
    ("Dyer Ave @ W 34 St", "Dyer Ave @ 34 St"),
    ("Broadway @ 6 Ave / 33 St", "broadway  @ 6 ave @ 33 st"),
])
def test_normalize_name_matches_variants(a, b):
    assert cl.normalize_name(a) == cl.normalize_name(b)


def test_normalize_keeps_different_streets_apart():
    assert cl.normalize_name("8 Ave @ 34 St") != cl.normalize_name("8 Ave @ 33 St")
    assert cl.normalize_name("West Broadway @ Houston St") != cl.normalize_name(
        "Broadway @ Houston St")


# --- resolution ----------------------------------------------------------------------

CHOSEN = [("8th Ave @ 31st St", 40.750297, -73.99483)]


def test_resolves_by_name(raw):
    got = cl.resolve_chosen(cl.parse_cameras(raw), CHOSEN)
    assert [c.id for c in got] == ["ec9ffb62-e3bf-4352-8bcf-7c9adf5fbe9c"]


def test_id_change_resolves_to_new_id():
    cams = [cam("new-id", "8 Ave @ 31 St", 40.750297, -73.99483)]
    assert [c.id for c in cl.resolve_chosen(cams, CHOSEN)] == ["new-id"]


def test_rename_resolves_by_nearest_coordinates():
    cams = [cam("far", "Somewhere Else", 40.7600, -73.9800),
            cam("renamed", "8 Av at W 31", 40.75031, -73.99480)]
    assert [c.id for c in cl.resolve_chosen(cams, CHOSEN)] == ["renamed"]


def test_nothing_close_stays_unresolved():
    cams = [cam("x", "Other", 40.7520, -73.9900)]  # ~450 m away, different name
    assert cl.resolve_chosen(cams, CHOSEN) == []


def test_name_match_far_away_is_rejected():
    cams = [cam("reused", "8th Ave @ 31st St", 40.7650, -73.9800)]
    assert cl.resolve_chosen(cams, CHOSEN) == []


def test_duplicate_names_pick_nearest():
    cams = [cam("far", "8 Ave @ 31 St", 40.7510, -73.9945),
            cam("near", "8 Ave @ 31 St", 40.75030, -73.99483)]
    assert [c.id for c in cl.resolve_chosen(cams, CHOSEN)] == ["near"]


def test_two_chosen_on_one_camera_keeps_one():
    cams = [cam("only", "8 Ave @ 31 St", 40.750297, -73.99483)]
    chosen = CHOSEN + [("Renamed Corner", 40.75030, -73.99483)]
    assert [c.id for c in cl.resolve_chosen(cams, chosen)] == ["only"]


def test_offline_camera_still_resolves():
    cams = [cam("off", "8th Ave @ 31st St", 40.750297, -73.99483, online=False)]
    got = cl.resolve_chosen(cams, CHOSEN)
    assert [c.id for c in got] == ["off"] and got[0].is_online is False


def test_chosen_list_has_nine_unique_cameras_in_area():
    assert len(cl.CHOSEN) == 9
    assert len({cl.normalize_name(n) for n, _, _ in cl.CHOSEN}) == 9
    min_lat, min_lon, max_lat, max_lon = PENN
    assert all(min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
               for _, lat, lon in cl.CHOSEN)


# --- scrape / file io ----------------------------------------------------------------


def test_scrape_includes_chosen_camera_that_drifted_outside_box(raw):
    edge = [("Edge Cam", PENN[0] + 0.0001, -73.990)]
    drifted = {**raw[2], "name": "Edge Cam", "latitude": PENN[0] - 0.0001,
               "longitude": -73.990}  # ~22 m from its stored spot, just outside the box
    with client_for(serve([drifted, *raw[3:6]])) as c:
        cams = cl.scrape(c, URL, PENN, edge)
    assert not cl.in_bbox(cl.parse_camera(drifted), PENN)
    assert drifted["id"] in {c.id for c in cams}


def test_scrape_with_empty_area_raises(raw):
    with client_for(serve(raw[:2])) as c, pytest.raises(cl.CameraListError):
        cl.scrape(c, URL, PENN)


def test_write_is_sorted_and_round_trips(tmp_path, raw):
    out = tmp_path / "cameras.json"
    cams = cl.parse_cameras(raw)
    cl.write_cameras(cams, out)
    back = cl.read_cameras(out)
    assert [c.name for c in back] == sorted(c.name for c in cams)
    assert {c.id for c in back} == {c.id for c in cams}
    assert list(tmp_path.iterdir()) == [out]  # no temp files left behind


def test_write_refuses_empty_list(tmp_path):
    out = tmp_path / "cameras.json"
    out.write_text("[]")
    with pytest.raises(cl.CameraListError):
        cl.write_cameras([], out)


def _patch_client(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(cl.httpx, "Client",
                        lambda *a, **k: real(transport=httpx.MockTransport(handler)))


def test_main_failed_fetch_leaves_file_untouched(tmp_path, monkeypatch):
    out = tmp_path / "cameras.json"
    out.write_text("GOOD")
    _patch_client(monkeypatch, serve({}, 500))
    assert cl.main(["--out", str(out)]) == 1
    assert out.read_text() == "GOOD"


def test_main_empty_area_leaves_file_untouched(tmp_path, monkeypatch, raw):
    out = tmp_path / "cameras.json"
    out.write_text("GOOD")
    _patch_client(monkeypatch, serve(raw[:2]))
    assert cl.main(["--out", str(out)]) == 1
    assert out.read_text() == "GOOD"


def test_main_fails_when_too_few_chosen_resolve(tmp_path, monkeypatch, raw):
    out = tmp_path / "cameras.json"
    _patch_client(monkeypatch, serve(raw))  # only 4 of the 10 chosen are in the sample
    assert cl.main(["--out", str(out)]) == 1
    assert out.exists()


def test_load_cameras_falls_back_to_file(tmp_path, raw):
    path = tmp_path / "cameras.json"
    cl.write_cameras(cl.parse_cameras(raw), path)
    with client_for(serve({}, 500)) as c:
        got = cl.load_cameras(refresh=True, client=c, path=path)
    assert "ec9ffb62-e3bf-4352-8bcf-7c9adf5fbe9c" in {c.id for c in got}


def test_load_cameras_prefers_live_ids(tmp_path, raw):
    path = tmp_path / "cameras.json"
    cl.write_cameras(cl.parse_cameras(raw), path)
    live = [{**r, "id": f"new-{r['id']}"} for r in raw]
    with client_for(serve(live)) as c:
        got = cl.load_cameras(refresh=True, client=c, path=path)
    assert got and all(c.id.startswith("new-") for c in got)


def test_excluded_cameras_are_left_out_of_the_scrape(raw):
    assert "8 Ave @ 34 St" in cl.EXCLUDED
    assert all(cl.normalize_name(n) not in {cl.normalize_name(x) for x in cl.EXCLUDED}
               for n, _, _ in cl.CHOSEN)
    with client_for(lambda r: httpx.Response(200, json=raw)) as c:
        names = {cam.name for cam in cl.scrape(c, URL, PENN)}
    assert "8 Ave @ 34 St" not in names and "8th Ave @ 31st St" in names
