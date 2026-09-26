"""Rule-based retiming (F9): Event -> common.schemas.Recommendation.

Bounds: keep min ped walk + clearance, cycle length unchanged,
max 20% change per phase. A human approves every change.
"""

# TODO: rules per event type (see docs/plan.md, "Retiming rules")
