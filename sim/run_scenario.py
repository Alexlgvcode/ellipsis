"""Run default (A) vs recommended (B) plan with an injected blockage (F10).

Blockage via TraCI vehicle.setStop at the event lane/time.
15 simulated minutes, 3 seeds each, A and B in parallel processes.
Outputs: avg delay per vehicle, max queue on blocked approach,
throughput, queue clear time.
"""

# TODO: build scenario, run A/B via TraCI, return common.schemas.SimResult
