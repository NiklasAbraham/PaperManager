import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import * as insights from "../api/insights";
import type { ReportDetail, ReportSummary } from "../api/insights";
import Reports from "./Reports";
import ReportView from "./ReportView";

vi.mock("../api/insights");
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, apiFetch: vi.fn() };
});

function summary(over: Partial<ReportSummary> = {}): ReportSummary {
  return {
    id: "r1",
    title: "Protein language models",
    question: "What do my papers say about protein language models?",
    project_id: null,
    project_name: "Thesis",
    status: "done",
    stage: null,
    progress: 100,
    model: "fast",
    length: "standard",
    owner: "niklas",
    created_at: "2026-11-10T09:00:00+00:00",
    updated_at: "2026-11-10T09:05:00+00:00",
    finished_at: "2026-11-10T09:05:00+00:00",
    paper_count: 12,
    word_count: 3400,
    error: null,
    ...over,
  };
}

function detail(over: Partial<ReportDetail> = {}): ReportDetail {
  return {
    ...summary(),
    markdown: "# Heading\n\nESM models learn structure [[1]](/paper/p1) and see [the docs](https://example.org/docs).",
    steps: [],
    papers: [{ id: "p1", title: "Evolutionary-scale prediction", year: 2023, n: 1 }],
    ...over,
  };
}

const OPTIONS = {
  models: [
    { id: "fast", label: "Claude Haiku 4.5", available: true },
    { id: "claude", label: "Claude Sonnet 4.6", available: false },
  ],
  lengths: ["short", "standard", "long"] as ("short" | "standard" | "long")[],
  default_model: "fast",
};

describe("Reports list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(insights.getReportOptions).mockResolvedValue(OPTIONS);
    vi.mocked(client.apiFetch).mockResolvedValue([{ id: "proj1", name: "Thesis" }]);
    vi.mocked(insights.listReports).mockResolvedValue([summary()]);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("lists reports with status, project and counts and links to the viewer", async () => {
    render(<MemoryRouter><Reports /></MemoryRouter>);
    const link = await screen.findByRole("link", { name: "Protein language models" });
    expect(link).toHaveAttribute("href", "/reports/r1");
    expect(screen.getByText("done")).toBeInTheDocument();
    expect(screen.getByText("Project: Thesis")).toBeInTheDocument();
    expect(screen.getByText("12 papers")).toBeInTheDocument();
    expect(screen.getByText("3,400 words")).toBeInTheDocument();
  });

  it("says what will appear when there are no reports", async () => {
    vi.mocked(insights.listReports).mockResolvedValue([]);
    render(<MemoryRouter><Reports /></MemoryRouter>);
    expect(await screen.findByText("No reports yet")).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    vi.mocked(insights.listReports).mockRejectedValue(new Error("boom"));
    render(<MemoryRouter><Reports /></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });

  it("submits the form with question, project, length and model, and shows the new row", async () => {
    const user = userEvent.setup();
    vi.mocked(insights.listReports).mockResolvedValue([]);
    vi.mocked(insights.createReport).mockResolvedValue(
      summary({ id: "r2", title: null, question: "What is new?", status: "queued", progress: 0, project_id: "proj1" }),
    );
    render(<MemoryRouter><Reports /></MemoryRouter>);
    await screen.findByText("No reports yet");
    await screen.findByRole("option", { name: "Thesis" });

    const submit = screen.getByRole("button", { name: "Write report" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Question"), "  What is new?  ");
    await user.selectOptions(screen.getByLabelText(/Project/), "proj1");
    await user.click(screen.getByRole("button", { name: "Long" }));
    expect(screen.getByRole("option", { name: /Claude Sonnet 4.6/ })).toBeDisabled();
    await user.click(submit);

    await waitFor(() =>
      expect(insights.createReport).toHaveBeenCalledWith({ question: "What is new?", project_id: "proj1", length: "long", model: "fast" }),
    );
    expect(await screen.findByRole("link", { name: "What is new?" })).toHaveAttribute("href", "/reports/r2");
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });

  it("polls while a report is running and stops when none is active", async () => {
    vi.useFakeTimers();
    vi.mocked(insights.listReports)
      .mockResolvedValueOnce([summary({ status: "running", progress: 30, stage: "Reading papers" })])
      .mockResolvedValueOnce([summary({ status: "running", progress: 60, stage: "Writing sections" })])
      .mockResolvedValue([summary({ status: "done" })]);
    render(<MemoryRouter><Reports /></MemoryRouter>);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText(/Reading papers/)).toBeInTheDocument();
    expect(insights.listReports).toHaveBeenCalledTimes(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(insights.listReports).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/Writing sections/)).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(insights.listReports).toHaveBeenCalledTimes(3);
    expect(screen.getByText("done")).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(insights.listReports).toHaveBeenCalledTimes(3);
  });

  it("clears the poll timer on unmount", async () => {
    vi.useFakeTimers();
    vi.mocked(insights.listReports).mockResolvedValue([summary({ status: "running", progress: 10 })]);
    const { unmount } = render(<MemoryRouter><Reports /></MemoryRouter>);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    unmount();
    const n = vi.mocked(insights.listReports).mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(insights.listReports).toHaveBeenCalledTimes(n);
  });
});

describe("ReportView", () => {
  function renderView() {
    return render(
      <MemoryRouter initialEntries={["/reports/r1"]}>
        <Routes>
          <Route path="/reports/:id" element={<ReportView />} />
          <Route path="/reports" element={<p>list page</p>} />
          <Route path="/paper/:id" element={<p>paper page</p>} />
        </Routes>
      </MemoryRouter>,
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(insights.getReport).mockResolvedValue(detail());
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders the markdown with library links as router links and external links in a new tab", async () => {
    const user = userEvent.setup();
    renderView();
    expect(await screen.findByRole("heading", { level: 1, name: "Protein language models" })).toBeInTheDocument();
    const article = screen.getByRole("article", { name: "Report" });
    const paperLink = Array.from(article.querySelectorAll("a")).find((a) => a.getAttribute("href") === "/paper/p1")!;
    expect(paperLink).toBeTruthy();
    expect(paperLink).not.toHaveAttribute("target");
    const ext = screen.getByRole("link", { name: "the docs" });
    expect(ext).toHaveAttribute("target", "_blank");
    expect(ext).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByRole("link", { name: "Evolutionary-scale prediction" })).toHaveAttribute("href", "/paper/p1");
    expect(screen.getByRole("button", { name: "Export Markdown" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export HTML" })).toBeInTheDocument();
    await user.click(paperLink);
    expect(await screen.findByText("paper page")).toBeInTheDocument();
  });

  it("exports in both formats", async () => {
    const user = userEvent.setup();
    vi.mocked(insights.downloadReport).mockResolvedValue(undefined);
    renderView();
    await user.click(await screen.findByRole("button", { name: "Export Markdown" }));
    await user.click(screen.getByRole("button", { name: "Export HTML" }));
    expect(insights.downloadReport).toHaveBeenNthCalledWith(1, "r1", "md");
    expect(insights.downloadReport).toHaveBeenNthCalledWith(2, "r1", "html");
  });

  it("deletes after confirmation and returns to the list", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(insights.deleteReport).mockResolvedValue(undefined);
    renderView();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(insights.deleteReport).toHaveBeenCalledWith("r1"));
    expect(await screen.findByText("list page")).toBeInTheDocument();
  });

  it("does not delete when the confirmation is refused", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderView();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    expect(insights.deleteReport).not.toHaveBeenCalled();
  });

  it("shows progress and steps while running, polls, and can cancel", async () => {
    vi.useFakeTimers();
    vi.mocked(insights.getReport)
      .mockResolvedValueOnce(
        detail({ status: "running", progress: 40, stage: "Reading evidence", markdown: null, steps: [{ ts: "2026-11-10T09:01:00+00:00", message: "Planned 5 sections" }], papers: [] }),
      )
      .mockResolvedValue(detail());
    vi.mocked(insights.cancelReport).mockResolvedValue(summary({ status: "cancelled" }));
    render(
      <MemoryRouter initialEntries={["/reports/r1"]}>
        <Routes><Route path="/reports/:id" element={<ReportView />} /></Routes>
      </MemoryRouter>,
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByText("Planned 5 sections")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export Markdown" })).not.toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
    expect(insights.getReport).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Export Markdown" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(insights.getReport).toHaveBeenCalledTimes(2);
  });

  it("calls cancelReport from the Cancel button", async () => {
    const user = userEvent.setup();
    vi.mocked(insights.getReport).mockResolvedValue(detail({ status: "queued", progress: 0, markdown: null, papers: [] }));
    vi.mocked(insights.cancelReport).mockResolvedValue(summary({ status: "cancelled" }));
    renderView();
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(insights.cancelReport).toHaveBeenCalledWith("r1"));
    expect(await screen.findByText("This report was cancelled.")).toBeInTheDocument();
  });

  it("shows the error of a failed report", async () => {
    vi.mocked(insights.getReport).mockResolvedValue(detail({ status: "failed", error: "Interrupted by a server restart", markdown: null }));
    renderView();
    expect(await screen.findByRole("alert")).toHaveTextContent("Interrupted by a server restart");
  });
});
