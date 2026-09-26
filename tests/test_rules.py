import yaml


def test_rules_yaml_has_thresholds(repo_root):
    rules = yaml.safe_load((repo_root / "events" / "rules.yaml").read_text())
    for key in ("double_parked", "stopped_in_lane", "blocked_box", "frozen_feed"):
        assert rules["dwell_s"][key] > 0
    # travel-lane stops must outlast a signal cycle, or red lights fire alerts
    assert rules["dwell_s"]["stopped_in_lane"] > rules["signal_cycle_s"]
