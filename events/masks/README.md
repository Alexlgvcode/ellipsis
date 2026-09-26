# Lane masks

One file per camera, `<camera-id>.json`, drawn on the reference frame saved next
to it as `<camera-id>.jpg`. Coordinates are pixels in the 352x240 frame.

```json
{
  "camera_id": "<id>",
  "name": "8th Ave @ 33rd St",
  "frame_size": [352, 240],
  "zones": [
    {"name": "parking_left", "type": "curb", "polygon": [[116, 50], [128, 50], [142, 135], [104, 135]]}
  ]
}
```

| Zone type | Meaning | Events |
|---|---|---|
| `curb` | Legal parking / curb lane | none (legally parked) |
| `curb_adjacent` | Travel lane next to the curb or parking lane | double parked |
| `travel` | Other travel lanes | stopped in lane |
| `box` | Intersection box (and crosswalk) | blocked box |
| `bus_stop` | Bus stop | longer wait threshold |
| `ignore` | Taxi stands, far background, anywhere detections aren't trusted | none |

Optional `"traffic": "away"` (default) or `"toward"`: which way traffic drives relative to the
camera. The event engine uses it to tell which stopped vehicle is at the front of a queue.

A vehicle's zone is looked up at the **bottom-center of its box** (where it touches
the road). Outside every polygon the zone is `none`. Where polygons overlap:
`ignore` > `bus_stop` > `box` > `curb` > `curb_adjacent` > `travel`.

## Current cameras

| Camera | Why it's here |
|---|---|
| 8th Ave @ 33rd St | Floating parking lane (left) + lanes next to it and the bike docks: double parking vs legal parking |
| 7 Ave @ 36 St | Long straight avenue, parked cars on the left, deliveries/police stopping by the right planters |
| 8 Ave @ 34 St | Looks straight down into the intersection: blocked box |
| 8th Ave @ 31st St | Penn Station taxi stand as an `ignore` zone, so waiting cabs aren't alerts |
| Broadway @ 38 St | Garment district: parked cars on the left, trucks stopping in the right lane |
| 7 Ave @ 32 St | Wide avenue: far block's curb lane; crosswalk and approach lanes as travel (red-light queue) |
| 7 Ave @ 34 St | Facing north, traffic **toward** the camera; 34th St crossing as the box |
| 6 Ave @ 34 St | Lane next to the bike-lane buffer, middle lanes, right curb lane, box |
| 6 Ave @ 30 St | Parking along the right curb and the lane next to it |
| Broadway @ 6 Ave / 33 St | Mostly plaza, one Broadway lane and the 33rd St crossing; rarely fires |

## Adding or fixing a mask

Use the editor:

```bash
python -m events.mask_editor      # then open http://127.0.0.1:8765
```

- Pick the camera (● = has a mask). Any camera with recorded frames in `data/frames/` is listed.
- Click a zone to select it, drag its square corner handles, drag a round mid-edge handle to add
  a point, ⌥/Alt-click a corner to remove it, arrow keys nudge the last corner by 1 px.
- *+ New zone* → click the corners → click the first point or press Enter.
- Drag the slider to check the mask on other recorded frames; tick *save this frame as
  reference* to make the frame on screen the camera's reference frame.
- *Save mask* validates and writes `<camera-id>.json` (and the `.jpg` if ticked). Then run
  `pytest tests/test_masks.py`, and add a vehicle you can see to `KNOWN_VEHICLES` there.

To render overlays without the editor:
`python -m events.masks overlay <camera-id> --frame a.jpg --frame b.jpg` (→ `runs/masks/`).

Cameras that pan or zoom: compare against the reference frame and pause that camera's
rules when the view has moved.
