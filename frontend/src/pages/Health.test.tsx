import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as insights from "../api/insights";
import type { SystemHealth } from "../api/insights";
import Health from "./Health";

vi.mock("../api/insights");
const auth = vi.hoisted(() => ({ useAuth: vi.fn() }));
vi.mock("../contexts/AuthContext", () => auth);

function health(over: Partial<SystemHealth> = {}): SystemHealth {
  return {
    generated_at: "2026-11-12T10:00:00+00:00",
    status: "degraded",
    checks: [
      { id: "backend", label: "Backend", status: "ok", summary: "Up for 3 h", details: { python: "3.11.9", pool: { size: 40, busy: 2 } }, checked_at: "2026-11-12T10:00:00+00:00", latency_ms: 1 },
      { id: "neo4j", label: "Neo4j", status: "warn", summary: "Slow: 900 ms", details: null, checked_at: "2026-11-12T10:00:00+00:00", latency_ms: 900 },
      { id: "llm:openai", label: "OpenAI", status: "off", summary: "Not configured", details: null, checked_at: "2026-11-12T10:00:00+00:00", latency_ms: null },
    ],
    version: { app: "dev", git_sha: "abcdef1234567", git_branch: "main", python: "3.11.9", started_at: "2026-11-12T07:00:00+00:00", uptime_s: 93784 },
    tokens_today: { calls: 14, errors: 1, input_tokens: 12000, output_tokens: 800, cost_usd: 0.42 },
    recent_errors: [{ ts: "2026-11-12 09:58:01", logger: "services.ai", level: "ERROR", message: "Summary failed: timeout" }],
    sweepers: [{ name: "concept-map-sweeper", alive: true, last_run: "2026-11-12T09:55:00+00:00", last_ok: true, last_error: null, interval_s: 600 }],
    audit: { actions_24h: 7, last: [{ ts: "2026-11-12T09:00:00+00:00", username: "niklas", action_type: "upload", entity_type: "paper" }] },
    ...over,
  };
}

function renderPage() {
  return render(<MemoryRouter><Health /></MemoryRouter>);
}

describe("Health", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(insights.getSystemHealth).mockResolvedValue(health());
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("tells non-admins they cannot see it and makes no request", () => {
    auth.useAuth.mockReturnValue({ username: "anna", isAdmin: false, isLoading: false });
    renderPage();
    expect(screen.getByText("Only admins can see the system health.")).toBeInTheDocument();
    expect(insights.getSystemHealth).not.toHaveBeenCalled();
  });

  it("renders the banner, checks, sweepers, spend, errors, audit and version for admins", async () => {
    const user = userEvent.setup();
    auth.useAuth.mockReturnValue({ username: "root", isAdmin: true, isLoading: false });
    renderPage();
    expect(await screen.findByText(/Degraded/)).toBeInTheDocument();
    expect(insights.getSystemHealth).toHaveBeenCalledWith(false);

    const backend = screen.getByTestId("check-backend");
    expect(backend).toHaveTextContent("Up for 3 h");
    expect(backend.querySelector('[data-status="ok"]')).not.toBeNull();
    expect(screen.getByTestId("check-neo4j").querySelector('[data-status="warn"]')).not.toBeNull();
    expect(screen.getByTestId("check-llm:openai").querySelector('[data-status="off"]')).not.toBeNull();

    expect(screen.queryByText("python")).not.toBeInTheDocument();
    await user.click(backend.querySelector("button")!);
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText('{"size":40,"busy":2}')).toBeInTheDocument();

    expect(screen.getByText("concept-map-sweeper")).toBeInTheDocument();
    expect(screen.getByText("10 min")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Tokens" })).toHaveAttribute("href", "/tokens");
    expect(screen.getByText("$0.42")).toBeInTheDocument();
    expect(screen.getByText("7 actions in 24 h")).toBeInTheDocument();
    expect(screen.getByText("upload")).toBeInTheDocument();

    expect(screen.queryByText(/Summary failed: timeout/)).toBeInTheDocument(); // newest line is previewed
    await user.click(screen.getByRole("button", { name: /Show 1/ }));
    expect(screen.getByText("ERROR")).toBeInTheDocument();

    const footer = screen.getByLabelText("Version");
    expect(footer).toHaveTextContent("Commit abcdef1");
    expect(footer).toHaveTextContent("Branch main");
    expect(footer).toHaveTextContent("Up 1 d 2 h");
  });

  it("refreshes with refresh=true from the button", async () => {
    const user = userEvent.setup();
    auth.useAuth.mockReturnValue({ username: "root", isAdmin: true, isLoading: false });
    renderPage();
    await screen.findByText(/Degraded/);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(insights.getSystemHealth).toHaveBeenLastCalledWith(true));
  });

  it("shows an error with retry when the request fails", async () => {
    auth.useAuth.mockReturnValue({ username: "root", isAdmin: true, isLoading: false });
    vi.mocked(insights.getSystemHealth).mockRejectedValue(new Error("API 500: down"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("down");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("reloads every minute while visible and stops on unmount", async () => {
    vi.useFakeTimers();
    auth.useAuth.mockReturnValue({ username: "root", isAdmin: true, isLoading: false });
    const { unmount } = renderPage();
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(insights.getSystemHealth).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(insights.getSystemHealth).toHaveBeenCalledTimes(2);
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(insights.getSystemHealth).toHaveBeenCalledTimes(2);
  });
});
