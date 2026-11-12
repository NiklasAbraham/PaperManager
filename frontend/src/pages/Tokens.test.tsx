import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as insights from "../api/insights";
import type { TokenCallRow, TokenSummary } from "../api/insights";
import Tokens from "./Tokens";

vi.mock("../api/insights");

function call(id: number, over: Partial<TokenCallRow> = {}): TokenCallRow {
  return {
    id,
    ts: "2026-11-12T09:00:00+00:00",
    feature: "summary",
    label: "services.ai.summarize_paper",
    provider: "anthropic",
    model: "claude-haiku-4-5",
    input_tokens: 12000,
    output_tokens: 800,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    cost_usd: 0.0123,
    price_known: true,
    user: "niklas",
    paper_id: "p1",
    ok: true,
    error: null,
    latency_ms: 1500,
    streamed: false,
    estimated: false,
    ...over,
  };
}

function summary(over: Partial<TokenSummary> = {}): TokenSummary {
  return {
    range: { since: "2026-10-14T00:00:00+00:00", until: "2026-11-12T10:00:00+00:00", days: 30 },
    scope: { user: null, is_admin: true },
    totals: {
      calls: 40,
      errors: 2,
      input_tokens: 1_500_000,
      output_tokens: 250_000,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
      cost_usd: 12.4,
      billed_usd: 12.4,
      subscription_usd: 0,
      unknown_price_calls: 3,
    },
    today: { calls: 5, errors: 0, input_tokens: 1000, output_tokens: 500, cost_usd: 0.42 },
    by_day: [
      { day: "2026-11-10", calls: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0 },
      { day: "2026-11-11", calls: 10, input_tokens: 4000, output_tokens: 1000, cost_usd: 1.5 },
      { day: "2026-11-12", calls: 5, input_tokens: 1000, output_tokens: 500, cost_usd: 0.42 },
    ],
    by_week: [{ week: "2026-W46", start: "2026-11-09", calls: 15, input_tokens: 5000, output_tokens: 1500, cost_usd: 1.92 }],
    by_feature: [
      { feature: "summary", calls: 30, errors: 2, input_tokens: 1_000_000, output_tokens: 100_000, cost_usd: 9.1, avg_latency_ms: 2300 },
      { feature: "knowledge-chat", calls: 10, errors: 0, input_tokens: 500_000, output_tokens: 150_000, cost_usd: 3.3, avg_latency_ms: 800 },
    ],
    by_model: [
      { model: "claude-haiku-4-5", provider: "anthropic", calls: 35, input_tokens: 1, output_tokens: 1, cost_usd: 12.4, price_known: true },
      { model: "mystery-model", provider: "anthropic-gateway", calls: 3, input_tokens: 1, output_tokens: 1, cost_usd: 0, price_known: false },
      { model: "gemma-3", provider: "litellm", calls: 2, input_tokens: 1, output_tokens: 1, cost_usd: 0, price_known: true },
    ],
    by_provider: [{ provider: "anthropic", calls: 35, cost_usd: 12.4 }],
    by_user: [
      { user: "niklas", calls: 30, input_tokens: 1, output_tokens: 1, cost_usd: 10 },
      { user: "alice", calls: 10, input_tokens: 1, output_tokens: 1, cost_usd: 2.4 },
    ],
    top_calls: [call(1, { cost_usd: 2.5 }), call(2, { ok: false, error: "RateLimitError: slow down" })],
    top_papers: [
      { paper_id: "p1", title: "Attention Is All You Need", calls: 4, input_tokens: 1, output_tokens: 1, cost_usd: 0.8 },
      { paper_id: "p2", title: null, calls: 1, input_tokens: 1, output_tokens: 1, cost_usd: 0.1 },
    ],
    unknown_models: ["mystery-model"],
    prices_as_of: "2026-11-12",
    ...over,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <Tokens />
    </MemoryRouter>,
  );
}

describe("Tokens", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(insights.getTokenSummary).mockResolvedValue(summary());
    vi.mocked(insights.getTokenCalls).mockResolvedValue({ calls: [call(10), call(11)], total: 3 });
  });

  it("renders totals, warning, chart and tables from the summary", async () => {
    renderPage();
    const dl = await screen.findByLabelText("Totals");
    expect(within(dl).getByText("$12.40")).toBeInTheDocument();
    expect(within(dl).getByText("$0.42")).toBeInTheDocument();
    expect(within(dl).getByText("40")).toBeInTheDocument();
    expect(within(dl).getByText("1.5M")).toBeInTheDocument();
    expect(within(dl).getByText("250k")).toBeInTheDocument();

    expect(screen.getByRole("alert")).toHaveTextContent(/3 calls have an unknown price.*mystery-model/);

    // Chart: one bar per day, zero day included, with a tooltip text.
    expect(screen.getAllByTestId("bar")).toHaveLength(3);
    expect(screen.getByRole("img", { name: "11 Nov 2026: 10 calls, 5k tokens, $1.50" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "10 Nov 2026: 0 calls, 0 tokens, $0.00" })).toBeInTheDocument();
    expect(screen.getByText(/Prices as of 2026-11-12; LiteLLM is counted as free/)).toBeInTheDocument();

    const byFeature = screen.getByRole("table", { name: "Usage by feature" });
    expect(within(byFeature).getByText("knowledge-chat")).toBeInTheDocument();
    expect(within(byFeature).getByText("$9.10")).toBeInTheDocument();

    const byModel = screen.getByRole("table", { name: "Usage by model" });
    expect(within(byModel).getByText("unknown price")).toBeInTheDocument();
    expect(within(byModel).getByText("free")).toBeInTheDocument();

    expect(within(screen.getByRole("table", { name: "Usage by user" })).getByText("alice")).toBeInTheDocument();

    const top = screen.getByRole("table", { name: "The most expensive calls in this range" });
    expect(within(top).getByText("$2.50")).toBeInTheDocument();
    expect(within(top).getByText("error").closest("[title]")).toHaveAttribute("title", "RateLimitError: slow down");

    const papers = screen.getByRole("table", { name: "Papers that caused the most cost" });
    expect(within(papers).getByRole("link", { name: "Attention Is All You Need" })).toHaveAttribute("href", "/paper/p1");
    expect(within(papers).getByText("(deleted paper)")).toBeInTheDocument();
  });

  it("shows billed and subscription equivalent when the subscription was used", async () => {
    const s = summary();
    s.totals = { ...s.totals, cost_usd: 16, billed_usd: 12.5, subscription_usd: 3.5 };
    vi.mocked(insights.getTokenSummary).mockResolvedValue(s);
    renderPage();
    const dl = await screen.findByLabelText("Totals");
    expect(within(dl).getByText("$12.50")).toBeInTheDocument();
    expect(within(dl).getByText(/\$3\.50 subscription-equivalent/)).toBeInTheDocument();
  });

  it("reloads with the new range and switches to weeks for 90 days", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByLabelText("Totals");
    expect(insights.getTokenSummary).toHaveBeenLastCalledWith(expect.objectContaining({ days: 30 }));

    await user.click(screen.getByRole("button", { name: "7 days" }));
    await waitFor(() => expect(insights.getTokenSummary).toHaveBeenLastCalledWith(expect.objectContaining({ days: 7 })));
    expect(insights.getTokenCalls).toHaveBeenLastCalledWith(expect.objectContaining({ days: 7, offset: 0 }));

    await user.click(screen.getByRole("button", { name: "90 days" }));
    await waitFor(() => expect(insights.getTokenSummary).toHaveBeenLastCalledWith(expect.objectContaining({ days: 90 })));
    await waitFor(() => expect(screen.getAllByTestId("bar")).toHaveLength(1));
    expect(screen.getByText("Cost per week")).toBeInTheDocument();
  });

  it("filters by user for admins and hides the user controls for others", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage();
    const select = await screen.findByLabelText("User");
    await user.selectOptions(select, "alice");
    await waitFor(() => expect(insights.getTokenSummary).toHaveBeenLastCalledWith(expect.objectContaining({ user: "alice" })));
    unmount();

    vi.mocked(insights.getTokenSummary).mockResolvedValue(summary({ scope: { user: "bob", is_admin: false }, by_user: [] }));
    renderPage();
    await screen.findByLabelText("Totals");
    expect(screen.queryByLabelText("User")).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Usage by user" })).not.toBeInTheDocument();
  });

  it("pages through recent calls with Load more", async () => {
    const user = userEvent.setup();
    vi.mocked(insights.getTokenCalls)
      .mockResolvedValueOnce({ calls: [call(10), call(11)], total: 3 })
      .mockResolvedValueOnce({ calls: [call(12, { feature: "concepts" })], total: 3 });
    renderPage();
    const more = await screen.findByRole("button", { name: "Load more" });
    await user.click(more);
    await waitFor(() => expect(insights.getTokenCalls).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 2 })));
    const recent = screen.getByRole("table", { name: "Recent calls, newest first" });
    await waitFor(() => expect(within(recent).getByText("concepts")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("loads the price table on demand", async () => {
    const user = userEvent.setup();
    vi.mocked(insights.getTokenPrices).mockResolvedValue({
      as_of: "2026-11-12",
      litellm_free: true,
      models: [{ prefix: "claude-haiku-4-5", input: 1, output: 5, cache_write: 1.25, cache_read: 0.1 }],
    });
    renderPage();
    await screen.findByLabelText("Totals");
    expect(insights.getTokenPrices).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Show price table" }));
    const table = await screen.findByRole("table", { name: "Prices in USD per million tokens" });
    expect(within(table).getByText("claude-haiku-4-5")).toBeInTheDocument();
  });

  it("explains an empty ledger", async () => {
    vi.mocked(insights.getTokenSummary).mockResolvedValue(
      summary({
        totals: { calls: 0, errors: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, cost_usd: 0, billed_usd: 0, subscription_usd: 0, unknown_price_calls: 0 },
        unknown_models: [],
        by_feature: [],
        by_model: [],
        by_user: [],
        top_calls: [],
        top_papers: [],
      }),
    );
    vi.mocked(insights.getTokenCalls).mockResolvedValue({ calls: [], total: 0 });
    renderPage();
    expect(await screen.findByText("No calls in this range")).toBeInTheDocument();
  });

  it("shows an error with a retry", async () => {
    vi.mocked(insights.getTokenSummary).mockRejectedValueOnce(new Error("API 500: boom"));
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("API 500: boom");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByLabelText("Totals")).toBeInTheDocument();
  });
});
