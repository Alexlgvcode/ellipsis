# SUMO network — Midtown Manhattan

9th Ave to 5th Ave, 29th St to 39th St, plus Dyer Ave (Lincoln Tunnel). The
baseline is a pre-timed **90 s** cycle (15 Penn FEIS ch. 16; confirmed on 9 of
10 of our cameras). Every parameter is traced in
[`sim/sources/sources.yaml`](../sources/sources.yaml).

## Commands

From the repo root, with `pip install -e ".[sim]"` and `SUMO_HOME` set (the
`eclipse-sumo` wheel sets this for you):

```bash
# 1. Download the OSM extract (gitignored) and build midtown.net.xml
python -m sim.network.build --fetch

# 2. Seeded corridor flows + randomTrips.py background -> midtown.rou.xml
python -m sim.routes.build_routes

# 3. Structure + 15-minute headless run
python -m sim.network.validate

# 4. Also 0.7x / 1.3x, seed replay, blockage smoke
python -m sim.network.validate --full

# 5. GUI (lights on 8th Ave and 34th St)
sumo-gui -c sim/network/midtown.sumocfg
```

Makefile aliases: `make sim-network`, `make sim-routes`, `make sim-validate`,
`make sim-gui`.

Rebuild without re-downloading OSM:

```bash
python -m sim.network.build --skip-osm
```

Measure green windows from recorded frames (writes `sim/sources/measurements.json`):

```bash
python scripts/measure_signals.py --frames data/frames
```

Refresh Open Data extracts (already committed):

```bash
python -m sim.sources.fetch_open_data
python -m sim.sources.extract_feis     # downloads Appendix H to /tmp if needed
```

## What gets committed

| File | Role |
|---|---|
| `midtown.net.xml` | Network after `netconvert` + `fixes.yaml` + program `lanewatch` |
| `midtown.tls.xml` | The `lanewatch` programs as an additional file |
| `midtown.sumocfg` | 300 s warm-up + 900 s (15 min), seed 42 |
| `tls_nodes.json` | Readable name, lat/lon, FEIS id, LPI / exclusive flags |
| `../routes/midtown.rou.xml` | Weekday midday demand |
| `../sources/*.json` | LPI, exclusive ped, crosswalks, TA-T7 2019 |

`midtown.osm.xml` and `sim/results/*` are gitignored.

## Assumptions (summary)

| Parameter | Value | Status |
|---|---|---|
| Cycle | 90 s, static / pre-timed | verified (FEIS + footage) |
| Yellow / all-red | 3 s / 2 s | assumed (ITE at 25 mph) |
| LPI | 7 s at DOT-listed intersections | verified (Open Data `xc4v-ntf4`) |
| Exclusive ped | 7 Ave @ 32 St, 24 s | verified (`8kuj-2n3u`) |
| Ped walk / clearance | 7 s + length / 3.5 ft/s | verified (MUTCD 4E) |
| Avenue / street split | 0.62 / 0.38 of remaining green | assumed; TA-T7-checked |
| Broadway 33–36 St | closed to vehicles | verified (DOT plaza) |
| 34th St | curb bus/taxi lane; left turns banned | verified (FEIS) |
| Demand | FEIS midday bands × 0.89 | verified (MTA CRZ −11%) |
| Midtown in Motion | not modeled | pre-timed plan as published |

Full register: [`sim/sources/sources.yaml`](../sources/sources.yaml).

## Extent

`sim/network/bbox.py`: `(40.7455, -73.9985, 40.7545, -73.9845)`
(south, west, north, east). Covers all 10 chosen cameras plus one signal beyond
each side.
