"""Scrape the NYC DOT camera list into data/cameras.json.

Source: https://webcams.nyctmc.org/api/cameras/  (public, undocumented)
Fields: id, name, latitude, longitude, area, isOnline, imageUrl

Camera IDs can change: never hardcode them. Match chosen cameras by name
and coordinates at startup.

    python -m ingest.camera_list --area penn
"""

# TODO: fetch list, filter to area bbox (common.config.AREAS), write data/cameras.json
# TODO: resolve chosen cameras by name / nearest coordinates


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
