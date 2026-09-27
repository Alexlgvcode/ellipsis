import { CAMERAS } from "../test/fixtures";
import { bearing, distance, offsetPath, parseCameraName, parseSignalId, pathLength, queuePath, toLngLat } from "./grid";

describe("grid", () => {
  it("lands every avenue camera within 25 m of its real position", () => {
    for (const cam of CAMERAS) {
      const pos = parseCameraName(cam.name);
      if (!pos || pos.avenue === "Broadway") continue;
      expect(distance(toLngLat(pos.ax, pos.st), [cam.lon, cam.lat])).toBeLessThan(25);
    }
  });

  it("parses camera names and signal ids", () => {
    expect(parseCameraName("8th Ave @ 33rd St")).toMatchObject({ ax: 0, st: 33, flow: 1 });
    expect(parseCameraName("7 Ave @ 34 St")).toMatchObject({ ax: 1, st: 34, flow: -1 });
    expect(parseCameraName("Broadway @ 38 St")).toMatchObject({ st: 38, avenue: "Broadway" });
    expect(parseCameraName("Dyer Ave @ W 34 St")).toBeNull();
    expect(parseSignalId("tls_8av_32st")).toMatchObject({ ax: 0, st: 32, label: "8 Ave @ 32 St" });
  });

  it("builds an upstream queue of the requested length, against the flow", () => {
    const pos = parseCameraName("8th Ave @ 33rd St")!;
    const start = toLngLat(pos.ax, pos.st);
    const path = queuePath(start, pos, 160);
    expect(pathLength(path)).toBeGreaterThan(150);
    expect(pathLength(path)).toBeLessThan(170);
    expect(path.at(-1)![1]).toBeLessThan(start[1]); // 8 Av runs uptown, so the queue backs up south
  });
});

it("offsets a path sideways without changing its length much", () => {
  const pos = parseCameraName("8th Ave @ 33rd St")!;
  const path = queuePath(toLngLat(pos.ax, pos.st), pos, 200);
  const right = offsetPath(path, 4);
  expect(distance(path[3], right[3])).toBeCloseTo(4, 0);
  expect(Math.abs(pathLength(right) - pathLength(path))).toBeLessThan(2);
  expect(bearing([0, 0], [0, 1])).toBeCloseTo(0);
  expect(bearing([0, 0], [1, 0])).toBeCloseTo(90);
});
