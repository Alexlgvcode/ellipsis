import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { REPO } from "../test/fixtures";
import { DWELL_S } from "./rules";

it("dwell thresholds match events/rules.yaml", () => {
  const yaml = readFileSync(resolve(REPO, "events/rules.yaml"), "utf8");
  const block = yaml.split("dwell_s:")[1].split(/\n\S/)[0];
  const fromYaml = Object.fromEntries([...block.matchAll(/^\s+(\w+):\s*(\d+)/gm)].map((m) => [m[1], Number(m[2])]));
  // rules.yaml also has zone rules (e.g. bus_stop) that aren't event types; compare event types only.
  const forEvents = Object.fromEntries(Object.keys(DWELL_S).map((k) => [k, fromYaml[k]]));
  expect(forEvents).toEqual(DWELL_S);
});
