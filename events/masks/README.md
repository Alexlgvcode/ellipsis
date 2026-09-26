# Lane masks

One file per camera: `<camera-id>.json`, drawn once on a reference frame.

Zone types: `curb`, `curb_adjacent`, `travel`, `box`, `bus_stop`, `ignore`.

```json
{
  "camera_id": "<id>",
  "frame_size": [352, 240],
  "zones": [
    {"name": "curb_east", "type": "curb", "polygon": [[x, y], [x, y], [x, y]]}
  ]
}
```

Cameras that pan or zoom: disable their masks when the view changes.
