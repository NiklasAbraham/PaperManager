import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";
import { resetDashboardCache } from "./useDashboardData";
import * as api from "./api";
import type { DashboardData, TopicMapData } from "./api";

vi.mock("./api", () => ({ fetchDashboard: vi.fn(), fetchTopicMap: vi.fn() }));
// jsdom has no canvas; the map's drawing is covered by the helper tests and the screenshots.
vi.mock("./TopicMap", () => ({ default: () => <div data-testid="map" /> }));

const dash: DashboardData = {
  total: 100, references: 900, added_7d: 12, added_30d: 85,
  added_weekly: Array.from({ length: 12 }, (_, i) => ({ week_start: `2026-0${(i % 9) + 1}-01`, count: i })),
  reading: { unread: 80, reading: 5, read: 15 },
  top_topics: [{ name: "Protein design", count: 30 }, { name: "Docking", count: 9 }],
  projects: [{ id: "p1", name: "Thesis", count: 40, read: 4, reading: 1 }],
};
const map: TopicMapData = {
  state: "ready", points: [], projects: [{ id: "p1", name: "Thesis", color: "#eda100", count: 40 }],
  clusters: [{ id: 0, label: "Protein Design", color: "#2a78d6", x: 0.5, y: 0.5, size: 10, library: 5 }],
};

function setup(variant: "a" | "b" | "c" = "b", onFilter = vi.fn()) {
  render(<MemoryRouter><Dashboard variant={variant} title="Library" onFilter={onFilter} /></MemoryRouter>);
  return onFilter;
}

beforeEach(() => {
  resetDashboardCache();
  localStorage.clear();
  vi.mocked(api.fetchDashboard).mockResolvedValue(dash);
  vi.mocked(api.fetchTopicMap).mockResolvedValue(map);
});

describe("Dashboard", () => {
  it("shows the week's count and the month", async () => {
    setup();
    expect(await screen.findByText("this month", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText(/85 this month/)).toBeInTheDocument();
  });

  it("clicking a reading segment, a topic or a project sets that filter", async () => {
    const onFilter = setup("b");
    await userEvent.click((await screen.findAllByRole("button", { name: /5 reading/ }))[0]);
    expect(onFilter).toHaveBeenCalledWith("reading_status", "reading");
    await userEvent.click(screen.getByRole("button", { name: /Protein design/ }));
    expect(onFilter).toHaveBeenCalledWith("topic", "Protein design");
    await userEvent.click(screen.getByRole("button", { name: /Thesis/ }));
    expect(onFilter).toHaveBeenCalledWith("project_id", "p1");
  });

  it.each(["a", "b", "c"] as const)("variant %s renders stats and map", async (v) => {
    setup(v);
    expect(await screen.findByLabelText("Reading progress")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("map")).toBeInTheDocument());
  });

  it("remembers the collapsed map card", async () => {
    setup("b");
    await userEvent.click(await screen.findByRole("button", { name: /Topic map/ }));
    expect(localStorage.getItem("pm_dash_map_collapsed")).toBe("1");
    expect(screen.queryByTestId("map")).not.toBeInTheDocument();
  });

  it("hides every piece when an older backend answers 404 and keeps the title", async () => {
    vi.mocked(api.fetchDashboard).mockResolvedValue(null);
    vi.mocked(api.fetchTopicMap).mockResolvedValue(null);
    setup("b");
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Library" })).toBeInTheDocument();
      expect(screen.queryByLabelText("Reading progress")).not.toBeInTheDocument();
      expect(screen.queryByTestId("map")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Topic map")).not.toBeInTheDocument();
    });
  });

  it("says the layout is being built while the backend computes it", async () => {
    vi.mocked(api.fetchTopicMap).mockResolvedValue({ ...map, state: "building", points: [], clusters: [] });
    setup("b");
    expect(await screen.findByText("Laying out your library…")).toBeInTheDocument();
  });
});
