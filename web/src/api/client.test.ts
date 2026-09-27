import { chooseSource } from "./client";

const LIVE = "https://api.ellipsisnyc.tech";
const answer = (body: object, status = 200) =>
  (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;

it("the public site reads the live API when it answers with real events", async () => {
  expect(await chooseSource("", LIVE, answer({ status: "ok", mock_mode: false, source: "live" })))
    .toEqual({ source: "hosted", unreachable: false });
});

it("plays the recording, and says why, when the live API is down, erroring or in mock mode", async () => {
  const down = (async () => { throw new TypeError("Failed to fetch"); }) as unknown as typeof fetch;
  for (const f of [down, answer({}, 502), answer({ status: "ok", mock_mode: true })]) {
    expect(await chooseSource("", LIVE, f)).toEqual({ source: "demo", unreachable: true });
  }
});

it("?replay and ?sample ask for the recording, and a build without a live API never tries one", async () => {
  const never = (() => { throw new Error("shouldn't be called"); }) as unknown as typeof fetch;
  expect(await chooseSource("?replay", LIVE, never)).toEqual({ source: "demo", unreachable: false });
  expect(await chooseSource("?sample", LIVE, never)).toEqual({ source: "demo", unreachable: false });
  expect(await chooseSource("", null, never)).toEqual({ source: "demo", unreachable: false });
});
