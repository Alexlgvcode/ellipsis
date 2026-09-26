import yaml


def test_rules_yaml_has_thresholds(repo_root):
    rules = yaml.safe_load((repo_root / "events" / "rules.yaml").read_text())
    for key in ("double_parked", "stopped_in_lane", "blocked_box", "frozen_feed"):
        assert rules["dwell_s"][key] > 0
    # red-light waits: travel-lane stops wait longer than double parking, and the engine
    # also needs front-of-queue and a vehicle seen in most frames (see evaluation/)
    assert rules["dwell_s"]["stopped_in_lane"] > rules["dwell_s"]["double_parked"]
    assert 0 < rules["stationary"]["min_seen_frac"] < 1
