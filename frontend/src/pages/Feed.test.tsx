import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as feed from "../api/feed";
import type { FeedConfig, FeedDigest, FeedItem, FeedStatus } from "../api/feed";
import * as client from "../api/client";
import Feed from "./Feed";

vi.mock("../api/feed");
vi.mock("../api/client", () => ({ listProjects: vi.fn() }));

function item(over: Partial<FeedItem> = {}): FeedItem {
  return {
    id: "arxiv:2611.00001",
    source: "arxiv",
    title: "Sparse attention for long documents",
    authors: ["Ada Example", "Bo Sample"],
    abstract: "We study sparse attention on synthetic documents.",
    published: "2026-11-17T10:00:00Z",
    url: "https://example.invalid/abs/1",
    doi: null,
    categories: ["cs.LG"],
    score: 0.82,
    neighbours: [{ paper_id: "p1", title: "Library paper on attention", similarity: 0.71 }],
    in_library: false,
    library_paper_id: null,
    my_label: null,
    ...over,
  };
}

function digest(items: FeedItem[], over: Partial<FeedDigest> = {}): FeedDigest {
  return {
    mode: "classifier", total: items.length, days: 3, skip: 0, limit: 30, positives: 42, quality: null,
    configured: true, items, ...over,
  };
}

const status = (over: Partial<FeedStatus> = {}): FeedStatus => ({
  enabled: true, state: "idle", last_refresh: "2026-11-18T08:00:00+00:00", next_refresh: null, candidates: 240,
  embedded: 240, mode: "classifier", positives: 42, quality: null, error: null, ...over,
});

const config = (over: Partial<FeedConfig> = {}): FeedConfig => ({
  sources: ["arxiv"], arxiv_categories: ["cs.LG"], digest_days: 3, min_score: 0, ...over,
});

function renderPage() {
  return render(<MemoryRouter><Feed /></MemoryRouter>);
}

describe("Feed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(feed.getFeedStatus).mockResolvedValue(status());
    vi.mocked(feed.getFeedConfig).mockResolvedValue(config());
    vi.mocked(feed.listFeed).mockResolvedValue(digest([item()]));
    vi.mocked(client.listProjects).mockResolvedValue([{ id: "pr1", name: "Attention study" }]);
  });

  it("says the feed is off and asks for nothing else when the instance has it disabled", async () => {
    vi.mocked(feed.getFeedStatus).mockResolvedValue({ enabled: false });
    renderPage();
    expect(await screen.findByText("The paper feed is switched off")).toBeInTheDocument();
    expect(feed.listFeed).not.toHaveBeenCalled();
  });

  it("shows the setup panel with example chips on the first visit and saves what was chosen", async () => {
    const user = userEvent.setup();
    vi.mocked(feed.getFeedConfig).mockResolvedValue(config({ arxiv_categories: [] }));
    vi.mocked(feed.listFeed).mockResolvedValue(digest([], { configured: false, mode: "newest", positives: 0 }));
    vi.mocked(feed.putFeedConfig).mockImplementation(async (c) => c);
    renderPage();
    expect(await screen.findByText("What should the feed show?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ cs.LG" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ cs.CV" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ q-bio.BM" })).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();                                   // arXiv alone needs a category

    await user.click(screen.getByRole("button", { name: "+ cs.CV" }));
    await user.type(screen.getByLabelText("arXiv categories"), "stat.ML, math.CO{Enter}");
    const chosen = screen.getByRole("list", { name: "Chosen categories" });
    expect(within(chosen).getAllByRole("listitem").map((li) => li.textContent?.replace("×", ""))).toEqual(["cs.CV", "stat.ML", "math.CO"]);
    await user.click(within(chosen).getByRole("button", { name: "Remove math.CO" }));
    await user.click(screen.getByLabelText(/bioRxiv/));
    await user.selectOptions(screen.getByLabelText("Digest window"), "7");

    vi.mocked(feed.listFeed).mockResolvedValue(digest([item()]));
    await user.click(save);
    await waitFor(() => expect(feed.putFeedConfig).toHaveBeenCalledWith({
      sources: ["arxiv", "biorxiv"], arxiv_categories: ["cs.CV", "stat.ML"], digest_days: 7, min_score: 0,
    }));
    expect(await screen.findByText("Sparse attention for long documents")).toBeInTheDocument();
    expect(screen.queryByText("What should the feed show?")).not.toBeInTheDocument();
  });

  it("rejects a malformed category without calling the server", async () => {
    const user = userEvent.setup();
    vi.mocked(feed.getFeedConfig).mockResolvedValue(config({ arxiv_categories: [] }));
    vi.mocked(feed.listFeed).mockResolvedValue(digest([], { configured: false }));
    renderPage();
    await user.type(await screen.findByLabelText("arXiv categories"), "CS.LG{Enter}");
    expect(screen.getByRole("alert")).toHaveTextContent(/not an arXiv category/);
    expect(screen.queryByRole("list", { name: "Chosen categories" })).not.toBeInTheDocument();
  });

  it("renders ranked rows with score, authors, reason and a collapsible abstract", async () => {
    const user = userEvent.setup();
    vi.mocked(feed.listFeed).mockResolvedValue(digest([
      item(),
      item({ id: "biorxiv:10.0000/b1", source: "biorxiv", title: "A preprint on proteins", score: 0.4, neighbours: [] }),
    ]));
    renderPage();
    const list = await screen.findByRole("list", { name: "Papers" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: "Sparse attention for long documents" })).toHaveAttribute("href", "https://example.invalid/abs/1");
    expect(within(rows[0]).getByText(/Ada Example, Bo Sample/)).toBeInTheDocument();
    expect(within(rows[0]).getByRole("meter", { name: "Relevance" })).toHaveAttribute("aria-valuenow", "82");
    expect(within(rows[0]).getByRole("link", { name: "Library paper on attention" })).toHaveAttribute("href", "/paper/p1");
    expect(within(rows[1]).getByText("bioRxiv")).toBeInTheDocument();
    expect(within(rows[0]).queryByText(/synthetic documents/)).not.toBeInTheDocument();
    await user.click(within(rows[0]).getByRole("button", { name: "Show abstract" }));
    expect(within(rows[0]).getByText(/synthetic documents/)).toBeInTheDocument();
  });

  it("shows the status strip: last refresh, stored papers, ranking mode and the held-out AUC with its caveat", async () => {
    vi.mocked(feed.getFeedStatus).mockResolvedValue(status({ error: "arxiv cs.LG: HTTP 503" }));
    vi.mocked(feed.listFeed).mockResolvedValue(digest([item()], { quality: { auc: 0.874, positives: 42, held_out: 8 } }));
    renderPage();
    const strip = await screen.findByLabelText("Feed status");
    await waitFor(() => expect(strip).toHaveTextContent("Ranked by a model trained on 42 papers you liked"));
    expect(strip).toHaveTextContent("240 papers stored");
    expect(strip).toHaveTextContent("Held-out AUC 0.87");
    expect(strip).toHaveTextContent("A rough guide, not a promise");
    expect(strip).toHaveTextContent("HTTP 503");
  });

  it("names the cold-start modes", async () => {
    vi.mocked(feed.listFeed).mockResolvedValue(digest([item({ score: null })], { mode: "newest", positives: 0 }));
    renderPage();
    expect(await screen.findByText(/Newest first/)).toBeInTheDocument();
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("rates a paper, removes it from the list and keeps it when rated papers are shown", async () => {
    const user = userEvent.setup();
    vi.mocked(feed.rateFeedItem).mockResolvedValue({ id: "arxiv:2611.00001", my_label: 1 });
    renderPage();
    await screen.findByText("Sparse attention for long documents");
    await user.click(screen.getByRole("button", { name: "Good match" }));
    expect(feed.rateFeedItem).toHaveBeenCalledWith("arxiv:2611.00001", 1);
    await waitFor(() => expect(screen.queryByText("Sparse attention for long documents")).not.toBeInTheDocument());
    expect(await screen.findByText("Nothing to show yet")).toBeInTheDocument();

    vi.mocked(feed.listFeed).mockResolvedValue(digest([item({ my_label: 1 })]));
    await user.click(screen.getByLabelText("Show rated"));
    await waitFor(() => expect(feed.listFeed).toHaveBeenLastCalledWith(expect.objectContaining({ include_rated: true })));
    expect(await screen.findByRole("button", { name: "Good match" })).toHaveAttribute("aria-pressed", "true");
    vi.mocked(feed.rateFeedItem).mockResolvedValue({ id: "arxiv:2611.00001", my_label: -1 });
    await user.click(screen.getByRole("button", { name: "Not for me" }));
    expect(feed.rateFeedItem).toHaveBeenLastCalledWith("arxiv:2611.00001", -1);
    await waitFor(() => expect(screen.getByRole("button", { name: "Not for me" })).toHaveAttribute("aria-pressed", "true"));
  });

  it("dismisses a paper", async () => {
    const user = userEvent.setup();
    vi.mocked(feed.dismissFeedItem).mockResolvedValue({ id: "arxiv:2611.00001", my_label: 0 });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(feed.dismissFeedItem).toHaveBeenCalledWith("arxiv:2611.00001");
    await waitFor(() => expect(screen.queryByText("Sparse attention for long documents")).not.toBeInTheDocument());
  });

  it("adds a paper to the library, or straight into a project, and then shows it as in the library", async () => {
    const user = userEvent.setup();
    vi.mocked(feed.addFeedItem).mockResolvedValue({ id: "arxiv:2611.00001", my_label: 1, paper_id: "new1" });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Add to library" }));
    expect(feed.addFeedItem).toHaveBeenCalledWith("arxiv:2611.00001", undefined);
    const badge = await screen.findByRole("link", { name: "In your library" });
    expect(badge).toHaveAttribute("href", "/paper/new1");
    expect(screen.queryByRole("button", { name: "Add to library" })).not.toBeInTheDocument();
  });

  it("adds to a chosen project", async () => {
    const user = userEvent.setup();
    vi.mocked(feed.addFeedItem).mockResolvedValue({ id: "arxiv:2611.00001", my_label: 1, paper_id: "new2" });
    renderPage();
    await user.selectOptions(await screen.findByLabelText(/Add to project/), "pr1");
    expect(feed.addFeedItem).toHaveBeenCalledWith("arxiv:2611.00001", "pr1");
  });

  it("flags papers already in the library and offers no Add button for them", async () => {
    vi.mocked(feed.listFeed).mockResolvedValue(digest([item({ in_library: true, library_paper_id: "p9" })]));
    renderPage();
    expect(await screen.findByRole("link", { name: "In your library" })).toHaveAttribute("href", "/paper/p9");
    expect(screen.queryByRole("button", { name: "Add to library" })).not.toBeInTheDocument();
  });

  it("shows an error when a rating cannot be saved and keeps the paper", async () => {
    const user = userEvent.setup();
    vi.mocked(feed.rateFeedItem).mockRejectedValue(new Error("API 500: boom"));
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Not for me" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/);
    expect(screen.getByText("Sparse attention for long documents")).toBeInTheDocument();
  });

  it("loads more", async () => {
    const user = userEvent.setup();
    vi.mocked(feed.listFeed).mockResolvedValueOnce(digest([item()], { total: 2 }));
    vi.mocked(feed.listFeed).mockResolvedValueOnce(digest([item({ id: "arxiv:2611.00002", title: "Second paper" })], { total: 2, skip: 1 }));
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Show more" }));
    expect(feed.listFeed).toHaveBeenLastCalledWith(expect.objectContaining({ skip: 1 }));
    expect(await screen.findByText("Second paper")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("starts a refresh from the status strip", async () => {
    const user = userEvent.setup();
    vi.mocked(feed.refreshFeed).mockRejectedValue(new Error("API 409: A refresh is already running"));
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Refresh now" }));
    expect(feed.refreshFeed).toHaveBeenCalled();
    expect(await screen.findByText(/already running/)).toBeInTheDocument();
  });

  it("opens the settings again from the strip and cancels without saving", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Sparse attention for long documents");
    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByText("What should the feed show?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText("What should the feed show?")).not.toBeInTheDocument();
    expect(feed.putFeedConfig).not.toHaveBeenCalled();
  });
});
