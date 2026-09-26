# Routes / demand

Weekday midday (default) and Saturday midday profiles. Avenue and 34th Street
targets come from 15 Penn FEIS ch. 16, multiplied by the 0.89 congestion-pricing
factor (MTA: vehicle entries down 11%).

```bash
python -m sim.routes.build_routes
python -m sim.routes.build_routes --period saturday_midday --multiplier 1.0
```

`build_routes.py` writes corridor and bus flows, adds a seeded `randomTrips.py`
background (`--fringe-factor 8`, period 6 s), and runs `duarouter`. The seed is
42 (`volumes.yaml`).
