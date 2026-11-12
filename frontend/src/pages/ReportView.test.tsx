import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as insights from "../api/insights";
import type { ReportDetail } from "../api/insights";
import ReportView from "./ReportView";

vi.mock("../api/insights");

function detail(over: Partial<ReportDetail> = {}): ReportDetail {
  return {
    id: "r1",
    title: "Protein folding in the library",
    question: "What does my library say about folding?",
    project_id: null,
    project_name: "Thesis",
    status: "done",
    stage: null,
    progress: 100,
    model: "fast",
    length: "standard",
    owner: "niklas",
    created_at: "2026-11-12T08:00:00+00:00",
    updated_at: "2026-11-12T08:05:00+00:00",
    finished_at: "2026-11-12T08:05:00+00:00",
    paper_count: 2,
    word_count: 1234,
    error: null,
    markdown:
      "## Findings\n\nFolding is fast [[1]](/paper/p1) and see [the docs](https://example.org/docs).\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    steps: [],
    papers: [
      { id: "p2", title: "Second paper", year: 2023, n: 2 },
      { id: "p1", title: "First paper", year: 2021, n: 1 },
    ],
    ...over,
  };
}

function renderView(path = "/reports/r1") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/reports/:id" element={<ReportView />} />
        <Route path="/reports" element={<div>list page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ReportView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(insights.getReport).mockResolvedValue(detail());
    vi.mocked(insights.downloadReport).mockResolvedValue(undefined);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders the header, the markdown body with library links and the cited papers", async () => {
    renderView();
    expect(await screen.findByRole("heading", { level: 1, name: "Protein folding in the library" })).toBeInTheDocument();
    expect(screen.getByText("What does my library say about folding?")).toBeInTheDocument();
    expect(screen.getByText("Project: Thesis")).toBeInTheDocument();
    expect(screen.getByText("1,234 words")).toBeInTheDocument();

    const body = screen.getByRole("article", { name: "Report" });
    expect(within(body).getByRole("heading", { name: "Findings" })).toBeInTheDocument();
    const lib = within(body).getByRole("link", { name: "[1]" });
    expect(lib).toHaveAttribute("href", "/paper/p1");
    expect(lib).not.toHaveAttribute("target");
    const ext = within(body).getByRole("link", { name: "the docs" });
    expect(ext).toHaveAttribute("href", "https://example.org/docs");
    expect(ext).toHaveAttribute("target", "_blank");
    expect(ext).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(within(body).getByRole("table")).toBeInTheDocument();

    const cited = screen.getByRole("complementary", { name: "Cited papers" });
    const links = within(cited).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["First paper", "Second paper"]);
    expect(links[0]).toHaveAttribute("href", "/paper/p1");
  });

  it("exports Markdown and HTML", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Export Markdown" }));
    expect(insights.downloadReport).toHaveBeenCalledWith("r1", "md");
    await user.click(screen.getByRole("button", { name: "Export HTML" }));
    expect(insights.downloadReport).toHaveBeenCalledWith("r1", "html");
  });

  it("shows an export failure", async () => {
    vi.mocked(insights.downloadReport).mockRejectedValueOnce(new Error("API 404: gone"));
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Export HTML" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("API 404: gone");
  });

  it("polls while running, shows the steps and a Cancel button, then shows the body", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(insights.getReport)
      .mockResolvedValueOnce(
        detail({ status: "running", progress: 35, stage: "Reading papers", markdown: null, steps: [{ ts: "2026-11-12T08:01:00+00:00", message: "Found 12 candidate papers" }] }),
      )
      .mockResolvedValue(detail());
    renderView();

    expect(await screen.findByText("Found 12 candidate papers")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Report progress" })).toHaveAttribute("aria-valuenow", "35");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export Markdown" })).not.toBeInTheDocument();
    expect(insights.getReport).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2600);
    });
    expect(insights.getReport).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole("article", { name: "Report" })).toBeInTheDocument();

    // Done: polling stops.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    expect(insights.getReport).toHaveBeenCalledTimes(2);
  });

  it("cancels a running report", async () => {
    const running = detail({ status: "running", progress: 20, markdown: null });
    vi.mocked(insights.getReport).mockResolvedValue(running);
    vi.mocked(insights.cancelReport).mockResolvedValue({ ...running, status: "cancelled" });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(insights.cancelReport).toHaveBeenCalledWith("r1");
    expect(await screen.findByText("This report was cancelled.")).toBeInTheDocument();
  });

  it("deletes after a confirmation and goes back to the list", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    vi.mocked(insights.deleteReport).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderView();
    const del = await screen.findByRole("button", { name: "Delete" });
    await user.click(del);
    expect(insights.deleteReport).not.toHaveBeenCalled();
    await user.click(del);
    expect(confirm).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(insights.deleteReport).toHaveBeenCalledWith("r1"));
    expect(await screen.findByText("list page")).toBeInTheDocument();
  });

  it("shows the error of a failed report", async () => {
    vi.mocked(insights.getReport).mockResolvedValue(detail({ status: "failed", markdown: null, error: "Interrupted by a server restart" }));
    renderView();
    expect(await screen.findByRole("alert")).toHaveTextContent("Interrupted by a server restart");
  });

  it("shows a load error with a retry", async () => {
    vi.mocked(insights.getReport).mockRejectedValueOnce(new Error("API 404: not found"));
    const user = userEvent.setup();
    renderView();
    expect(await screen.findByRole("alert")).toHaveTextContent("API 404: not found");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Protein folding in the library" })).toBeInTheDocument();
  });
});
