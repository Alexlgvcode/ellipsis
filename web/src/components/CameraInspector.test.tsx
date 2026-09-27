import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { CAMERAS } from "../test/fixtures";
import { cameraView } from "../lib/incidents";
import { CameraInspector } from "./CameraInspector";

const cam = cameraView(CAMERAS.find((c) => c.name === "7 Ave @ 32 St")!);

describe("camera opened from the map", () => {
  it("shows the camera and its live feed, nothing about incidents", () => {
    render(<CameraInspector camera={cam} now={Date.now()} onClose={() => {}} />);
    expect(screen.getByRole("heading", { name: "7 Ave @ 32 St" })).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("Live camera")).toBeInTheDocument();
    expect(screen.getByAltText("Latest frame from 7 Ave @ 32 St")).toHaveAttribute("src", expect.stringContaining(cam.imageUrl!));
    expect(screen.queryByRole("button", { name: "At alert" })).toBeNull();   // no alert frame to switch to
    expect(screen.queryByText(/Traffic impact|Recommended response|conf\./)).toBeNull();
  });

  it("closes with the X or Escape", () => {
    const onClose = vi.fn();
    render(<CameraInspector camera={cam} now={Date.now()} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Close camera" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("marks an offline camera", () => {
    render(<CameraInspector camera={{ ...cam, state: "offline" }} now={Date.now()} onClose={() => {}} />);
    expect(screen.getAllByText(/OFFLINE/).length).toBeGreaterThan(0);
  });
});
