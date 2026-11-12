import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { SAVED_QUERIES_KEY } from "../components/graph/savedQueries";
import { SettingsProvider } from "../contexts/SettingsContext";
import Cypher from "./Cypher";
import Graph from "./Graph";

const mocks = vi.hoisted(() => ({
  graphData: vi.fn(),
  auth: { isAdmin: true },
}));

// force-graph needs canvas / WebGL: a chainable stand-in that records graphData calls.
vi.mock("force-graph", () => {
  const make = () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const proxy: any = new Proxy(function () {}, {
      get: (_t, prop) => {
        if (prop === "graphData") return (d: unknown) => { mocks.graphData(d); return proxy; };
        if (prop === "_destructor") return undefined;
        if (prop === "d3Force") return () => null;
        return () => proxy;
      },
      apply: () => proxy,
    });
    return proxy;
  };
  return { default: () => () => make() };
});

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../contexts/AuthContext", () => ({ useAuth: () => mocks.auth }));

const EXPLORER = {
  nodes: [{ id: "x1", label: "Explorer paper", type: "paper" }],
  links: [],
};

const NODE_RESULT = {
  columns: ["p", "r", "t"],
  rows: [{ p: { _labels: ["Paper"], title: "Flow" }, r: { _type: "ABOUT" }, t: { _labels: ["Topic"], name: "Diffusion" } }],
  row_count: 1,
  truncated: false,
  counters: { nodes_created: 0, nodes_deleted: 0, relationships_created: 0, relationships_deleted: 0, properties_set: 0 },
  nodes: [
    { id: "p1", label: "Flow", type: "paper" },
    { id: "t1", label: "Diffusion", type: "topic" },
  ],
  links: [{ source: "p1", target: "t1", type: "ABOUT" }],
  took_ms: 4,
};

const TABLE_RESULT = {
  ...NODE_RESULT,
  columns: ["title", "year"],
  rows: [{ title: "Attention Is All You Need", year: 2017 }],
  nodes: [],
  links: [],
};

let queryResponse: unknown = TABLE_RESULT;

function lastGraphData() {
  const calls = mocks.graphData.mock.calls;
  return calls[calls.length - 1]?.[0] as { nodes: { id: string }[]; links: unknown[] } | undefined;
}

function postedQueries() {
  return vi.mocked(apiFetch).mock.calls.filter(([path]) => path === "/graph/query");
}

function renderGraph(url = "/graph") {
  return render(
    <SettingsProvider>
      <MemoryRouter initialEntries={[url]}>
        <Graph />
      </MemoryRouter>
    </SettingsProvider>,
  );
}

const editor = () => screen.getByLabelText("Cypher query") as HTMLTextAreaElement;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mocks.auth.isAdmin = true;
  queryResponse = TABLE_RESULT;
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path.startsWith("/graph?")) return EXPLORER;
    if (path === "/graph/query") return queryResponse;
    if (path === "/cypher/schema") {
      return { labels: ["Paper"], relationship_types: ["CITES"], properties: { Paper: ["id", "title"] } };
    }
    if (path === "/cypher/assist") return { query: "MATCH (p:Paper) RETURN p LIMIT 3" };
    throw new Error(`unexpected ${path}`);
  });
});

describe("Graph page", () => {
  it("shows the explorer without the query panel by default", async () => {
    renderGraph();
    expect(await screen.findByText(/1 nodes · 0 edges/)).toBeInTheDocument();
    expect(screen.queryByTestId("query-panel")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Query" })).toBeInTheDocument();
    await waitFor(() => expect(lastGraphData()?.nodes.map(n => n.id)).toEqual(["x1"]));
  });

  it("opens the panel from ?view=query and preloads ?q=", async () => {
    renderGraph("/graph?view=query&q=" + encodeURIComponent("MATCH (n:Tag) RETURN n"));
    expect(await screen.findByTestId("query-panel")).toBeInTheDocument();
    expect(editor().value).toBe("MATCH (n:Tag) RETURN n");
  });

  it("opens and closes the panel with the Query button", async () => {
    const user = userEvent.setup();
    renderGraph();
    await screen.findByText(/1 nodes/);
    await user.click(screen.getByRole("button", { name: "Query" }));
    expect(screen.getByTestId("query-panel")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close query panel" }));
    expect(screen.queryByTestId("query-panel")).not.toBeInTheDocument();
  });

  it("runs read-only by default and shows the rows in the table", async () => {
    const user = userEvent.setup();
    renderGraph("/graph?view=query&q=" + encodeURIComponent("MATCH (p:Paper) RETURN p.title AS title, p.year AS year"));
    await user.click(await screen.findByRole("button", { name: /^Run/ }));

    expect(await screen.findByText("Attention Is All You Need")).toBeInTheDocument();
    expect(screen.getByText("2017")).toBeInTheDocument();
    expect(screen.getByText("1 row")).toBeInTheDocument();

    const [path, init] = postedQueries()[0];
    expect(path).toBe("/graph/query");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      query: "MATCH (p:Paper) RETURN p.title AS title, p.year AS year",
      read_only: true,
    });
    // no nodes in the result: the Table tab is active and the canvas keeps the explorer data
    expect(screen.getByRole("tab", { name: /^Table/ })).toHaveAttribute("aria-selected", "true");
    expect(lastGraphData()?.nodes.map(n => n.id)).toEqual(["x1"]);
  });

  it("runs on Ctrl+Enter", async () => {
    renderGraph("/graph?view=query&q=RETURN%201");
    fireEvent.keyDown(await screen.findByLabelText("Cypher query"), { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(postedQueries()).toHaveLength(1));
  });

  it("switches to the Graph tab for a node result and draws it in the canvas", async () => {
    const user = userEvent.setup();
    queryResponse = NODE_RESULT;
    renderGraph("/graph?view=query&q=" + encodeURIComponent("MATCH (p)-[r]->(t) RETURN p, r, t"));
    await screen.findByText(/1 nodes/);
    await user.click(screen.getByRole("button", { name: /^Run/ }));

    const graphTab = await screen.findByRole("tab", { name: /^Graph/ });
    expect(graphTab).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(lastGraphData()?.nodes.map(n => n.id)).toEqual(["p1", "t1"]));
    expect(screen.getByText(/2 nodes · 1 edges/)).toBeInTheDocument();

    // Table tab returns the explorer to the canvas
    await user.click(screen.getByRole("tab", { name: /^Table/ }));
    await waitFor(() => expect(lastGraphData()?.nodes.map(n => n.id)).toEqual(["x1"]));
    expect(screen.getByText("Diffusion", { exact: false })).toBeInTheDocument();
  });

  it("has a Back to full graph control while a result is drawn", async () => {
    const user = userEvent.setup();
    queryResponse = NODE_RESULT;
    renderGraph("/graph?view=query&q=" + encodeURIComponent("MATCH (p)-[r]->(t) RETURN p, r, t"));
    await screen.findByText(/1 nodes/);
    await user.click(screen.getByRole("button", { name: /^Run/ }));
    await user.click(await screen.findByRole("button", { name: "Back to full graph" }));
    await waitFor(() => expect(lastGraphData()?.nodes.map(n => n.id)).toEqual(["x1"]));
    expect(screen.getByRole("tab", { name: /^Table/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("button", { name: "Back to full graph" })).not.toBeInTheDocument();
  });

  it("asks once before allowing writes, then posts read_only false", async () => {
    const user = userEvent.setup();
    renderGraph("/graph?view=query&q=" + encodeURIComponent("MATCH (n:Tag) DETACH DELETE n"));
    await user.click(await screen.findByRole("checkbox", { name: /allow writes/i }));
    const dialog = screen.getByRole("alertdialog");
    expect(screen.getByRole("checkbox", { name: /allow writes/i })).not.toBeChecked();
    await user.click(within(dialog).getByRole("button", { name: "Allow writes" }));
    expect(screen.getByRole("checkbox", { name: /allow writes/i })).toBeChecked();

    await user.click(screen.getByRole("button", { name: /^Run/ }));
    await waitFor(() => expect(postedQueries()).toHaveLength(1));
    expect(JSON.parse((postedQueries()[0][1] as RequestInit).body as string).read_only).toBe(false);

    // switching off and on again does not ask a second time
    await user.click(screen.getByRole("checkbox", { name: /allow writes/i }));
    await user.click(screen.getByRole("checkbox", { name: /allow writes/i }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /allow writes/i })).toBeChecked();
  });

  it("explains a rejected write", async () => {
    const user = userEvent.setup();
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path.startsWith("/graph?")) return EXPLORER;
      throw new Error('API 400: {"detail":"Writing in read access mode not allowed."}');
    });
    renderGraph("/graph?view=query&q=CREATE%20(n)");
    await user.click(await screen.findByRole("button", { name: /^Run/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Writing in read access mode not allowed.");
    expect(alert).toHaveTextContent(/Allow writes/);
  });

  it("saves, loads and deletes queries through localStorage", async () => {
    const user = userEvent.setup();
    renderGraph("/graph?view=query&q=" + encodeURIComponent("MATCH (t:Topic) RETURN t"));
    await screen.findByTestId("query-panel");
    await user.click(screen.getByRole("button", { name: "Saved" }));
    await user.type(screen.getByLabelText("Name for the current query"), "All topics");
    await user.click(screen.getByRole("button", { name: "Save" }));

    const stored = JSON.parse(localStorage.getItem(SAVED_QUERIES_KEY)!);
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({ name: "All topics", query: "MATCH (t:Topic) RETURN t" });
    expect(typeof stored[0].saved_at).toBe("string");

    fireEvent.change(editor(), { target: { value: "RETURN 1" } });
    await user.click(screen.getByRole("button", { name: "All topics" }));
    expect(editor().value).toBe("MATCH (t:Topic) RETURN t");

    await user.click(screen.getByRole("button", { name: "Delete saved query All topics" }));
    expect(JSON.parse(localStorage.getItem(SAVED_QUERIES_KEY)!)).toEqual([]);
  });

  it("lists previously saved queries when the panel opens", async () => {
    const user = userEvent.setup();
    localStorage.setItem(SAVED_QUERIES_KEY, JSON.stringify([{ name: "Old one", query: "RETURN 7", saved_at: "2026-11-01T10:00:00.000Z" }]));
    renderGraph("/graph?view=query");
    await user.click(await screen.findByRole("button", { name: "Saved" }));
    await user.click(screen.getByRole("button", { name: "Old one" }));
    expect(editor().value).toBe("RETURN 7");
  });

  it("fills the editor from the example menu", async () => {
    const user = userEvent.setup();
    renderGraph("/graph?view=query");
    await user.click(await screen.findByRole("button", { name: "Examples" }));
    const list = screen.getByTestId("examples-list");
    expect(within(list).getByText("Graph views")).toBeInTheDocument();
    await user.click(within(list).getByRole("button", { name: "Papers with no notes yet" }));
    expect(editor().value).toContain("NOT (p)<-[:ABOUT]-(:Note)");
  });

  it("loads the schema lazily and generates a query with AI assist", async () => {
    const user = userEvent.setup();
    renderGraph("/graph?view=query");
    await screen.findByTestId("query-panel");
    expect(vi.mocked(apiFetch).mock.calls.some(([p]) => p === "/cypher/schema")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Schema" }));
    expect(await screen.findByText("title", { exact: false })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Describe the query in plain English"), "three papers");
    await user.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(editor().value).toBe("MATCH (p:Paper) RETURN p LIMIT 3"));
  });

  it("gives non-admins the explorer only", async () => {
    mocks.auth.isAdmin = false;
    renderGraph("/graph?view=query&q=RETURN%201");
    expect(await screen.findByText(/1 nodes · 0 edges/)).toBeInTheDocument();
    expect(screen.queryByTestId("query-panel")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Query" })).not.toBeInTheDocument();
    expect(postedQueries()).toHaveLength(0);
  });
});

describe("old /cypher route", () => {
  function Where() {
    const loc = useLocation();
    return <div data-testid="where">{loc.pathname + loc.search}</div>;
  }

  function renderAt(url: string) {
    return render(
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/cypher" element={<Cypher />} />
          <Route path="/graph" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("redirects to the query panel", () => {
    renderAt("/cypher");
    expect(screen.getByTestId("where")).toHaveTextContent("/graph?view=query");
  });

  it("keeps ?q=", () => {
    renderAt("/cypher?q=" + encodeURIComponent("MATCH (n) RETURN n"));
    const where = screen.getByTestId("where").textContent!;
    const params = new URLSearchParams(where.split("?")[1]);
    expect(params.get("view")).toBe("query");
    expect(params.get("q")).toBe("MATCH (n) RETURN n");
  });
});
