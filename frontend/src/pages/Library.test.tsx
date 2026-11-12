import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import { SettingsProvider } from "../contexts/SettingsContext";
import type { SearchResponse } from "../types";
import Library from "./Library";

// The upload button is its own feature; here only the project it was handed matters.
vi.mock("../components/PaperDrop", () => ({
  default: ({ defaultProjectId }: { defaultProjectId?: string }) => <div data-testid="paper-drop" data-project={defaultProjectId ?? ""} />,
}));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, apiFetch: vi.fn(), searchLibrary: vi.fn(), searchSuggest: vi.fn() };
});

const RESPONSE: SearchResponse = {
  results: [
    { id: "a", title: "Flow Matching for Generative Modeling", created_at: "2026-01-01", year: 2023, score: 9, matched_in: "paper",
      matched_fields: ["title"], title_marks: [[0, 4], [5, 13]], snippets: [], authors: ["Yaron Lipman"] },
    { id: "b", title: "Zeta paper", created_at: "2026-02-01", year: 2019, score: 3, matched_in: "note",
      matched_fields: ["note"], snippets: [{ field: "note", text: "compare flow matching", marks: [[8, 12]] }] },
  ],
  total: 2,
  mode: "hybrid",
  relaxed: false,
  took_ms: 42,
};

const LISTING: SearchResponse = {
  results: [
    { id: "p1", title: "Newest paper", created_at: "2026-11-01", year: 2026, score: 0, matched_in: "paper", authors: ["Ada Lovelace"] },
    { id: "p2", title: "Older paper", created_at: "2026-10-01", year: 2024, score: 0, matched_in: "paper", authors: ["Alan Turing"] },
  ],
  total: 1163,
};
const READING: SearchResponse = {
  results: [{ id: "r1", title: "Half-read paper", created_at: "2026-09-01", year: 2025, score: 0, matched_in: "paper", authors: ["Grace Hopper"] }],
  total: 1,
};

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.search}</div>;
}

function renderAt(url: string) {
  return render(
    <SettingsProvider>
      <MemoryRouter initialEntries={[url]}>
        <Library />
        <Where />
      </MemoryRouter>
    </SettingsProvider>,
  );
}

const searchCalls = () => vi.mocked(client.searchLibrary).mock.calls.map((c) => c[0]);
const listingCalls = () => searchCalls().filter((p) => p.get("reading_status") !== "reading" || p.has("q"));

describe("Library search", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.apiFetch).mockImplementation(async (path: string) => {
      if (path === "/projects") return [];
      if (path === "/stats") return null;
      if (path === "/papers") return [];
      return null;
    });
    vi.mocked(client.searchLibrary).mockResolvedValue(RESPONSE);
  });

  it("runs the query from the URL and keeps the server's relevance order", async () => {
    renderAt("/?q=flow%20matching");
    await waitFor(() => expect(screen.getAllByTestId("search-hit")).toHaveLength(2));
    const params = vi.mocked(client.searchLibrary).mock.calls[0][0];
    expect(params.get("q")).toBe("flow matching");
    expect(params.get("mode")).toBe("hybrid");
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    // "Zeta paper" stays second although a title sort would put "Flow…" first anyway and
    // a year sort would not: the client does not re-sort ranked hits.
    expect(titles).toEqual(["Flow Matching for Generative Modeling", "Zeta paper"]);
    expect(screen.getAllByText("Your note").length).toBeGreaterThan(0);
    expect(screen.getByPlaceholderText(/Search titles/)).toHaveValue("flow matching");
    expect(screen.getByLabelText("Sort results")).toHaveValue("relevance");
  });

  it("shows an empty state with ways out", async () => {
    vi.mocked(client.searchLibrary).mockResolvedValue({ ...RESPONSE, results: [], total: 0 });
    renderAt("/?q=xyzzy&tag=foo");
    await waitFor(() => expect(screen.getByText(/No papers match “xyzzy” with these filters/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Search cited references too" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Search by meaning" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove filters" })).toBeInTheDocument();
  });

  it("says when meaning search is still indexing", async () => {
    vi.mocked(client.searchLibrary).mockResolvedValue({
      ...RESPONSE, mode: "lexical",
      semantic: { state: "building", done: 100, todo: 8000, indexed: 100, papers: 8000, enabled: true, model_loaded: true },
    });
    renderAt("/?q=diffusion");
    await waitFor(() => expect(screen.getByText(/still indexing \(100 \/ 8000 papers\)/)).toBeInTheDocument());
  });

  it("keeps the year range from the URL (it feeds the filter) and shows it as a chip", async () => {
    renderAt("/?q=diffusion&year_min=2020&year_max=2022");
    await waitFor(() => expect(client.searchLibrary).toHaveBeenCalled());
    const params = vi.mocked(client.searchLibrary).mock.calls[0][0];
    expect(params.get("year_min")).toBe("2020");
    expect(params.get("year_max")).toBe("2022");
    expect(screen.getByTestId("where").textContent).toContain("year_min=2020");
    expect(screen.getByText("Year: 2020 to 2022")).toBeInTheDocument();
  });
});

describe("Library dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.apiFetch).mockImplementation(async (path: string) => {
      if (path === "/projects") return [{ id: "p-thesis", name: "Thesis", created_at: "2026-01-01" }];
      if (path === "/tags") return [{ id: "t", name: "diffusion" }];
      if (path === "/topics") return [{ id: "o", name: "Flow matching" }];
      return null;
    });
    vi.mocked(client.searchLibrary).mockImplementation(async (p: URLSearchParams) =>
      p.get("reading_status") === "reading" && !p.has("q") && p.get("limit") === "6" ? { ...READING, results: [] } : LISTING);
  });

  it("browses through /search, never /papers or /stats, and shows no stat tiles", async () => {
    renderAt("/");
    await waitFor(() => expect(screen.getByText("Newest paper")).toBeInTheDocument());
    const paths = vi.mocked(client.apiFetch).mock.calls.map((c) => c[0]);
    expect(paths).not.toContain("/papers");
    expect(paths).not.toContain("/stats");
    expect(paths.some((p) => String(p).startsWith("/venues"))).toBe(false);
    const listing = listingCalls()[0];
    expect(Object.fromEntries(listing)).toEqual({
      sort: "date_desc", skip: "0", limit: "50", include_references: "false", snippets: "0",
    });
    expect(screen.getByText(/· 1,163 papers/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recently added" })).toBeInTheDocument();
    expect(screen.queryByText("Reading progress")).not.toBeInTheDocument();
    expect(screen.queryByText("Papers by year")).not.toBeInTheDocument();
    expect(screen.queryByText("Venues")).not.toBeInTheDocument();
  });

  it("shows Continue reading only when the reading call returns rows", async () => {
    renderAt("/");
    await waitFor(() => expect(screen.getByText("Newest paper")).toBeInTheDocument());
    expect(screen.queryByText("Continue reading")).not.toBeInTheDocument();
    const reading = searchCalls().find((p) => p.get("reading_status") === "reading")!;
    expect(Object.fromEntries(reading)).toMatchObject({ sort: "updated_desc", limit: "6" });
  });

  it("lists the papers being read when there are some", async () => {
    vi.mocked(client.searchLibrary).mockImplementation(async (p: URLSearchParams) =>
      p.get("reading_status") === "reading" ? READING : LISTING);
    renderAt("/");
    await waitFor(() => expect(screen.getByText("Half-read paper")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Continue reading" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Half-read paper/ })).toHaveAttribute("href", "/paper/r1");
  });

  it("pages the listing on the server and sorts through the URL", async () => {
    renderAt("/");
    await waitFor(() => expect(screen.getByText("Newest paper")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(listingCalls().some((p) => p.get("skip") === "50")).toBe(true));
    fireEvent.change(screen.getByLabelText("Sort results"), { target: { value: "title_asc" } });
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("?sort=title_asc"));
    await waitFor(() => expect(listingCalls().some((p) => p.get("sort") === "title_asc" && p.get("skip") === "0")).toBe(true));
    expect(screen.getByRole("heading", { name: "All papers" })).toBeInTheDocument();
  });

  it("choosing Last 7 days in Filters puts added=7d in the URL and refetches", async () => {
    renderAt("/");
    await waitFor(() => expect(screen.getByText("Newest paper")).toBeInTheDocument());
    const before = listingCalls().length;
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    fireEvent.click(screen.getByRole("button", { name: "Last 7 days" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("?added=7d"));
    await waitFor(() => expect(listingCalls().length).toBeGreaterThan(before));
    const last = listingCalls().at(-1)!;
    expect(last.get("added_after")).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(screen.getByText("Added: last 7 days")).toBeInTheDocument();
    // the dashboard gives way to the filtered listing
    expect(screen.queryByText(/· 1,163 papers/)).not.toBeInTheDocument();
    expect(screen.getByText(/1,163/)).toBeInTheDocument();
  });

  it("Clear all removes every filter chip and the query", async () => {
    renderAt("/?q=flow&tag=a&has_pdf=1&added_from=2026-01-01&rating_min=3&sort=year_desc");
    await waitFor(() => expect(screen.getByText("Tag: a")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("?sort=year_desc"));
    expect(screen.queryByText("Tag: a")).not.toBeInTheDocument();
  });

  it("dismisses a single chip", async () => {
    renderAt("/?tag=a&has_pdf=1");
    await waitFor(() => expect(screen.getByText("Has PDF")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Remove Has PDF" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("?tag=a"));
  });

  it("hands the active project to the upload button", async () => {
    renderAt("/?project_id=p-thesis");
    await waitFor(() => expect(screen.getByText("Project: Thesis")).toBeInTheDocument());
    expect(screen.getByTestId("paper-drop")).toHaveAttribute("data-project", "p-thesis");
  });

  it("offers relevance in Filters only with a query", async () => {
    renderAt("/");
    await waitFor(() => expect(screen.getByText("Newest paper")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    const sort = screen.getByLabelText("Sort by") as HTMLSelectElement;
    expect([...sort.options].map((o) => o.value)).not.toContain("relevance");
  });
});
