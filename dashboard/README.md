# Dashboard

Operator UI (F7), built in Streamlit: a map with camera pins and a stopped-car heatmap, a live
alert feed, the selected alert with its snapshot, reason and live camera frame, and the signal
recommendation with its simulated effect. Full spec and design brief:
[docs/dashboard.md](../docs/dashboard.md).

```bash
make install      # after pulling: adds streamlit and the dashboard package
make api          # terminal 1, http://localhost:8000 (mock mode serves data/mock/)
make dashboard    # terminal 2, http://localhost:8501
```

Set `LW_API_URL` in `.env` if the API isn't on `http://localhost:8000`.

| File | What |
|---|---|
| `data.py` | API client and all data shaping (pins, heat, feed rows, reason text, snapshot targeting, recommendation card). No Streamlit, unit tested in `tests/test_dashboard.py` |
| `app.py` | Streamlit layout. Refreshes every 2 s inside a fragment, so the selection and map toggles survive |
| `theme.py` | ctOS-style colors and CSS, shared by the panels, map and snapshot overlays |

Notes:

- An alert is **active** if it was last seen within 5 minutes; in mock mode every alert is active.
- Heat sits at each active alert's camera, weighted by `min(duration / threshold, 5) x confidence`
  with thresholds from `events/rules.yaml`. Events carry a camera, not a street position, so heat
  shows as blobs at camera spots.
- The live camera frame loads straight from NYCTMC in the browser, refreshed every 5 s.
- Signal IDs in recommendations are placeholders until `signals/camera_signals.json` (#13).
