import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as feed from "../api/feed";
import * as similar from "../api/similar";
import type { SimilarHit, SimilarResult } from "../api/similar";
import { queryFromHit } from "../components/similar/queryFromHit";
import SimilarSearch from "./SimilarSearch";

vi.mock("../api/feed");
vi.mock("../api/similar", async (orig) => ({ ...(await orig<typeof import("../api/similar")>()), searchSimilar: vi.fn(), papersLike: vi.fn() }));

let features = new Set<string>();
vi.mock("../lib/features", () => ({ useFeatures: () => features, loadFeatures: vi.fn().mockResolvedValue(undefined) }));

const ABSTRACT = "Sparse attention for long documents. We study how sparse attention behaves on synthetic documents.";

function hit(over: Partial<SimilarHit> = {}): SimilarHit {
  return {
    source: "library", id: "p1", title: "Sparse attention in practice", authors: ["Ada Example", "Bo Sample"], year: 2024,
    venue: "Synthetic Venue", doi: null, url: "http://localhost/paper/p1", score: 0.83,
    snippet: "A short snippet of the abstract.", abstract: "The full abstract of the library paper, longer than the snippet shown first.",
    in_library: true, library_paper_id: "p1", my_label: null, ...over,
  };
}

function result(hits: SimilarHit[], over: Partial<SimilarResult> = {}): SimilarResult {
  return { available: true, reason: null, scope: "library", mode: "document", total: hits.length, hits, skipped: {}, ...over };
}

function feedHit(over: Partial<SimilarHit> = {}): SimilarHit {
  return hit({
    source: "feed", id: "arxiv:2611.00001", title: "A new preprint on sparse attention", url: "https://example.invalid/abs/1",
    published: "2026-11-17T10:00:00Z", year: 2026, venue: undefined, score: 0.71, in_library: false, library_paper_id: null,
    abstract: "Preprint abstract text, long enough to be expandable.", snippet: "Preprint abstract text…", ...over,
  });
}

function renderPage() {
  return render(<MemoryRouter><SimilarSearch /></MemoryRouter>);
}

async function typeAbstract(user: ReturnType<typeof userEvent.setup>, value = ABSTRACT) {
  const box = screen.getByLabelText("Abstract");
  await user.clear(box);
  await user.click(box);
  await user.paste(value);
  return box;
}

describe("SimilarSearch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    features = new Set();
    vi.mocked(similar.searchSimilar).mockResolvedValue(result([hit()]));
  });

  it("starts with an empty state and a search button that waits for enough text", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(screen.getByText("Nothing searched yet")).toBeInTheDocument();
    const box = screen.getByPlaceholderText("Paste or write an abstract: title and a paragraph work best");
    const button = screen.getByRole("button", { name: "Search" });
    expect(button).toBeDisabled();
    await user.type(box, "too short");
    expect(button).toBeDisabled();
    expect(screen.getByText("9 / 20,000")).toBeInTheDocument();
    await typeAbstract(user);
    expect(button).toBeEnabled();
    expect(similar.searchSimilar).not.toHaveBeenCalled();
  });

  it("without the feed there is no scope toggle and the search runs on the library", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(screen.queryByRole("group", { name: "Search in" })).not.toBeInTheDocument();
    await typeAbstract(user);
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(similar.searchSimilar).toHaveBeenCalledTimes(1));
    expect(similar.searchSimilar).toHaveBeenCalledWith({ text: ABSTRACT, k: 10, scope: "library", since: undefined });
  });

  it("with the feed on: scope toggle, date and result count go into the request", async () => {
    features = new Set(["feed"]);
    const user = userEvent.setup();
    renderPage();
    const group = screen.getByRole("group", { name: "Search in" });
    expect(within(group).getByRole("button", { name: "Both" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(group).getByRole("button", { name: "Feed" }));
    expect(within(group).getByRole("button", { name: "Feed" })).toHaveAttribute("aria-pressed", "true");
    await user.type(screen.getByLabelText("Published since"), "2026-10-01");
    await user.selectOptions(screen.getByLabelText("Results"), "20");
    await typeAbstract(user);
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(similar.searchSimilar).toHaveBeenCalled());
    expect(similar.searchSimilar).toHaveBeenCalledWith({ text: ABSTRACT, k: 20, scope: "feed", since: "2026-10-01" });
  });

  it("shows library and feed hits with score bar, badges and the right links", async () => {
    features = new Set(["feed"]);
    vi.mocked(similar.searchSimilar).mockResolvedValue(result([
      hit(),
      feedHit(),
      feedHit({ id: "arxiv:2611.00002", title: "Already kept preprint", in_library: true, library_paper_id: "p9", score: 0.6 }),
    ], { scope: "both" }));
    const user = userEvent.setup();
    renderPage();
    await typeAbstract(user);
    await user.click(screen.getByRole("button", { name: "Search" }));
    const list = await screen.findByRole("list", { name: "Similar papers" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);

    expect(within(rows[0]).getByRole("link", { name: "Sparse attention in practice" })).toHaveAttribute("href", "/paper/p1");
    expect(within(rows[0]).getByText("Library")).toBeInTheDocument();
    expect(within(rows[0]).getByRole("meter", { name: "Similarity" })).toHaveAttribute("aria-valuenow", "83");
    expect(within(rows[0]).getByText("0.83")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/Ada Example, Bo Sample/)).toBeInTheDocument();
    expect(within(rows[0]).queryByRole("button", { name: "Add to library" })).not.toBeInTheDocument();

    const ext = within(rows[1]).getByRole("link", { name: "A new preprint on sparse attention" });
    expect(ext).toHaveAttribute("href", "https://example.invalid/abs/1");
    expect(ext).toHaveAttribute("target", "_blank");
    expect(within(rows[1]).getByText("Feed")).toBeInTheDocument();
    expect(within(rows[1]).getByRole("button", { name: "Add to library" })).toBeInTheDocument();

    expect(within(rows[2]).getByRole("link", { name: /In your library/ })).toHaveAttribute("href", "/paper/p9");
    expect(within(rows[2]).queryByRole("button", { name: "Add to library" })).not.toBeInTheDocument();
  });

  it("expands the abstract of a hit", async () => {
    const user = userEvent.setup();
    renderPage();
    await typeAbstract(user);
    await user.click(screen.getByRole("button", { name: "Search" }));
    const more = await screen.findByRole("button", { name: "Show more" });
    expect(screen.getByText("A short snippet of the abstract.")).toBeInTheDocument();
    await user.click(more);
    expect(screen.getByText(/The full abstract of the library paper/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
  });

  it("'Use this paper as the query' puts title and abstract into the text box without searching", async () => {
    const user = userEvent.setup();
    renderPage();
    await typeAbstract(user);
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.click(await screen.findByRole("button", { name: "Use this paper as the query" }));
    const box = screen.getByLabelText("Abstract") as HTMLTextAreaElement;
    expect(box.value).toBe(queryFromHit(hit()));
    expect(box.value.startsWith("Sparse attention in practice\n\nThe full abstract")).toBe(true);
    expect(screen.getByText(/replaced by the paper you picked/)).toBeInTheDocument();
    expect(similar.searchSimilar).toHaveBeenCalledTimes(1);          // the user edits first
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(similar.searchSimilar).toHaveBeenCalledTimes(2);
    expect(vi.mocked(similar.searchSimilar).mock.calls[1][0].text).toBe(box.value);
  });

  it("adds a feed paper through the feed's endpoint and marks it as in the library", async () => {
    features = new Set(["feed"]);
    vi.mocked(similar.searchSimilar).mockResolvedValue(result([feedHit()], { scope: "both" }));
    vi.mocked(feed.addFeedItem).mockResolvedValue({ id: "arxiv:2611.00001", my_label: 1, paper_id: "p77" });
    const user = userEvent.setup();
    renderPage();
    await typeAbstract(user);
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.click(await screen.findByRole("button", { name: "Add to library" }));
    expect(feed.addFeedItem).toHaveBeenCalledWith("arxiv:2611.00001");
    const badge = await screen.findByRole("link", { name: /In your library/ });
    expect(badge).toHaveAttribute("href", "/paper/p77");
    expect(screen.queryByRole("button", { name: "Add to library" })).not.toBeInTheDocument();
  });

  it("says so when adding fails", async () => {
    features = new Set(["feed"]);
    vi.mocked(similar.searchSimilar).mockResolvedValue(result([feedHit()]));
    vi.mocked(feed.addFeedItem).mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderPage();
    await typeAbstract(user);
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.click(await screen.findByRole("button", { name: "Add to library" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    expect(screen.getByRole("button", { name: "Add to library" })).toBeInTheDocument();
  });

  it("explains an index that is still building and lets the user try again", async () => {
    vi.mocked(similar.searchSimilar).mockResolvedValueOnce(result([], { available: false, reason: "the library index is still being built" }));
    const user = userEvent.setup();
    renderPage();
    await typeAbstract(user);
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("The index is not ready for this search")).toBeInTheDocument();
    expect(screen.getByText(/the library index is still being built/)).toBeInTheDocument();
    vi.mocked(similar.searchSimilar).mockResolvedValueOnce(result([hit()]));
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("list", { name: "Similar papers" })).toBeInTheDocument();
    expect(screen.queryByText("The index is not ready for this search")).not.toBeInTheDocument();
  });

  it("shows an empty result and the notes of namespaces that were skipped", async () => {
    features = new Set(["feed"]);
    vi.mocked(similar.searchSimilar).mockResolvedValue(result([], { scope: "both", skipped: { feed: "no feed papers have been embedded yet" } }));
    const user = userEvent.setup();
    renderPage();
    await typeAbstract(user);
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No similar papers found")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Notes" })).toHaveTextContent("Not searched (feed): no feed papers have been embedded yet.");
  });

  it("shows an error with a retry", async () => {
    vi.mocked(similar.searchSimilar).mockRejectedValueOnce(new Error("API 500: server error"));
    const user = userEvent.setup();
    renderPage();
    await typeAbstract(user);
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("API 500");
    expect(screen.queryByText("Nothing searched yet")).not.toBeInTheDocument();
    vi.mocked(similar.searchSimilar).mockResolvedValueOnce(result([hit()]));
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("list", { name: "Similar papers" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("refuses a text over the limit", async () => {
    const user = userEvent.setup();
    renderPage();
    const box = screen.getByLabelText("Abstract");
    await user.click(box);
    await user.paste("x".repeat(20001));
    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
  });
});
