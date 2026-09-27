import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import { CAMERAS, EVENTS, RECS } from "./test/fixtures";

// MapLibre needs WebGL; the map is exercised in the browser, not in jsdom.
vi.mock("./components/MapShell", () => ({ MapShell: () => <div data-testid="map" /> }));

import App from "./App";

let apiDown = false;
let feedbackFails = false;
let saved: { event_id: string; action: string }[] = [];
function mockApi() {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (apiDown) throw new TypeError("Failed to fetch");
    const path = url.replace(/^\/api/, "");
    const fb = /^\/events\/([^/]+)\/feedback$/.exec(path);
    if (fb && init?.method === "POST") {
      if (feedbackFails) return new Response("", { status: 500 });
      const row = { event_id: decodeURIComponent(fb[1]), ...JSON.parse(String(init.body)) };
      saved = [...saved.filter((f) => f.event_id !== row.event_id), row];
      return new Response(JSON.stringify(row), { status: 201 });
    }
    const body =
      path === "/health" ? { status: "ok", mock_mode: true }
      : path === "/feedback" ? saved
      : path === "/cameras" ? CAMERAS
      : path.startsWith("/events") ? EVENTS
      : path.startsWith("/recommendations/") ? RECS[decodeURIComponent(path.split("/")[2])] : undefined;
    return body === undefined ? new Response("", { status: 404 }) : new Response(JSON.stringify(body), { status: 200 });
  }));
}

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
  apiDown = false; feedbackFails = false; saved = []; mockApi(); vi.useFakeTimers({ shouldAdvanceTime: true }); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const loaded = async () => { await screen.findByText("Active incidents"); };

it("shows the three mock incidents in the rail, sorted by severity, with no inspector open", async () => {
  render(<App />);
  await loaded();
  const rail = screen.getByRole("complementary", { name: "Active incidents" });
  const rows = within(rail).getAllByRole("button", { name: /elapsed/ });
  expect(rows.map((r) => r.getAttribute("aria-label")?.split(",")[0])).toEqual(["7 Ave @ 34 St", "8th Ave @ 33rd St", "7 Ave @ 34 St"]);
  expect(screen.getByText("SAMPLE DATA")).toBeInTheDocument();
  expect(screen.getByLabelText("ellipsis")).toBeInTheDocument();
  expect(screen.queryByRole("complementary", { name: /Incident at/ })).toBeNull();
});

it("selecting an incident opens the inspector with impact and the recommended response", async () => {
  render(<App />);
  await loaded();
  fireEvent.click(screen.getByRole("button", { name: /8th Ave @ 33rd St/ }));
  const insp = screen.getByRole("complementary", { name: "Incident at 8th Ave @ 33rd St" });
  expect(within(insp).getByText("Double parked vehicle")).toBeInTheDocument();
  expect(within(insp).getByText("21 vehicles")).toBeInTheDocument();
  expect(within(insp).getByText("Recommended is faster by 9.2s per vehicle")).toBeInTheDocument();
  expect(within(insp).getByRole("figure", { name: /Queue over time/ })).toBeInTheDocument();
  expect(within(insp).getByText("CAM-8AV-033")).toBeInTheDocument();
});

it("each demo incident says which side is faster, and by how much, on the card", async () => {
  render(<App />);
  await loaded();
  fireEvent.click(screen.getByRole("button", { name: /Stopped in lane/ }));
  expect(screen.getByText("Default is faster by 1.6s per vehicle")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Blocking the box/ }));
  expect(screen.getByText("Recommended is faster by 4.6s per vehicle")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /8th Ave @ 33rd St/ }));
  fireEvent.click(screen.getByRole("button", { name: /Open simulation/ }));
  expect(screen.getAllByRole("status").some((s) => s.textContent?.includes("Running scenario…"))).toBe(true);
  const base = screen.getByRole("region", { name: "Base close-up" });
  const simView = screen.getByRole("region", { name: "Sim close-up" });
  expect(within(base).getByText("45s")).toBeInTheDocument();
  expect(within(simView).getByText(/45s → 39s/)).toBeInTheDocument();
  expect(within(base).getByText("48.3s")).toBeInTheDocument();
  expect(within(simView).getByText("39.1s")).toBeInTheDocument();
  expect(within(simView).getByText("Improved")).toBeInTheDocument();
  const summary = screen.getByRole("complementary", { name: "Base versus sim summary" });
  expect(within(summary).getByText("Recommended is faster by 9.2s per vehicle")).toBeInTheDocument();
  await act(async () => { vi.advanceTimersByTime(10_500); });
  expect(within(summary).getByText("19%")).toBeInTheDocument();
  expect(within(summary).getByText("Improved northbound flow on 8 Ave")).toBeInTheDocument();
  expect(within(summary).getByRole("button", { name: "Base" })).toBeEnabled();
});

it("records the operator's decision; an accepted alert shows as applied (sim)", async () => {
  render(<App />);
  await loaded();
  fireEvent.click(screen.getByRole("button", { name: /8th Ave @ 33rd St/ }));
  const insp = screen.getByRole("complementary", { name: "Incident at 8th Ave @ 33rd St" });
  const group = within(insp).getByRole("group", { name: "Decide on this alert" });
  expect(within(insp).getByText("No decision yet")).toBeInTheDocument();

  await act(async () => { fireEvent.click(within(group).getByRole("button", { name: "Accept" })); });
  expect(saved).toEqual([{ event_id: "evt_mock_001", action: "accept" }]);
  expect(within(insp).getByRole("status")).toHaveTextContent("Applied (sim)");
  expect(within(group).getByRole("button", { name: "Accept" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: /8th Ave @ 33rd St, Double parked, Applied \(sim\)/ })).toBeInTheDocument();

  await act(async () => { fireEvent.click(within(group).getByRole("button", { name: "False positive" })); });
  expect(saved).toEqual([{ event_id: "evt_mock_001", action: "false_positive" }]);
  expect(within(insp).getByRole("status")).toHaveTextContent("False positive");
  expect(screen.getByText("2", { selector: ".rail-title .count" })).toBeInTheDocument();
});

it("shows decisions already saved in the API, e.g. after a reload", async () => {
  saved = [{ event_id: "evt_mock_002", action: "reject" }];
  render(<App />);
  await loaded();
  expect(screen.getByRole("button", { name: /7 Ave @ 34 St, Stopped in lane, Rejected/ })).toBeInTheDocument();
});

it("says so when a decision can't be saved, and keeps the old one", async () => {
  feedbackFails = true;
  render(<App />);
  await loaded();
  fireEvent.click(screen.getByRole("button", { name: /8th Ave @ 33rd St/ }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Reject" })); });
  expect(screen.getByRole("alert")).toHaveTextContent(/Couldn't save the decision/);
  expect(screen.getByText("No decision yet")).toBeInTheDocument();
});

it("keeps the last known state and shows a thin banner when the API drops", async () => {
  render(<App />);
  await loaded();
  apiDown = true;
  await act(async () => { vi.advanceTimersByTime(3000); });
  expect(await screen.findByText(/Connection lost\. Showing last known state/)).toBeInTheDocument();
  expect(screen.getByText("OFFLINE")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: /elapsed/ })).toHaveLength(3);
});

it("shows the empty state when there are no incidents", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const path = url.replace(/^\/api/, "");
    const body = path === "/health" ? { status: "ok", mock_mode: false } : path === "/cameras" ? CAMERAS : [];
    return new Response(JSON.stringify(body), { status: 200 });
  }));
  render(<App />);
  expect(await screen.findByText("No active incidents")).toBeInTheDocument();
  expect(screen.getByText("Traffic conditions are normal in this area.")).toBeInTheDocument();
  expect(screen.getByText("LIVE")).toBeInTheDocument();
});
