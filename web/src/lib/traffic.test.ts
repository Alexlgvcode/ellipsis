import { CAR_COLOR, INSET_MAX_QUEUE, carState, flowWord, insetScene } from "./traffic";

const SIM = { baselineDelay: 48.3, recommendedDelay: 39.1, savedPerVehicle: 9.2, improvementPct: 19, queueBefore: 21, queueAfter: 13 };

it("classifies cars by speed", () => {
  expect(carState(0, 11)).toBe("stopped");
  expect(carState(4, 11)).toBe("slowing");
  expect(carState(10, 11)).toBe("flowing");
  expect(Object.keys(CAR_COLOR)).toEqual(["stopped", "slowing", "flowing"]);
});

it("scales the close-ups from the simulated queues, same geometry, less pressure in the recommended plan", () => {
  const base = insetScene(SIM, 45, "base", "curb");
  const sim = insetScene(SIM, 39, "sim", "curb");
  expect(base.queuedCars).toBe(INSET_MAX_QUEUE);
  expect(sim.queuedCars).toBe(Math.round(13 * INSET_MAX_QUEUE / 21));
  expect(sim.pressure).toBeLessThan(base.pressure);
  expect([base.cycleS, base.blockage]).toEqual([sim.cycleS, sim.blockage]);
  expect([flowWord(SIM, "base"), flowWord(SIM, "sim")]).toEqual(["Congested", "Improved"]);
});
