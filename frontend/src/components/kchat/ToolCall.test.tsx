import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToolCall, Trace } from "./ToolCall";
import type { TraceStep } from "./types";

vi.mock("../../api/client", () => ({ apiUrl: (p: string) => `http://api${p}`, apiFetch: vi.fn() }));

const noop = () => {};

describe("ToolCall", () => {
  const cypher: TraceStep = {
    tool: "run_cypher", kind: "cypher", description: "Count papers per year", count: 12,
    cypher: "MATCH (p:Paper) RETURN p.year, count(*)", input: { query: "MATCH (p:Paper) RETURN p.year, count(*)", description: "Count papers per year" },
    result: '[{"p.year": 2024, "count(*)": 5}]',
  };

  it("is collapsed by default: label, summary and count, nothing else", () => {
    render(<ToolCall step={cypher} onPaper={noop} />);
    expect(screen.getByText("Graph")).toBeInTheDocument();
    expect(screen.getByText("Count papers per year")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/MATCH/)).toBeNull();
    expect(screen.queryByText(/2024/)).toBeNull();
  });

  it("expanded: the Cypher in a code block and the result preview in a scrollable pre", () => {
    const { container } = render(<ToolCall step={cypher} onPaper={noop} />);
    fireEvent.click(screen.getByRole("button"));
    expect(container.querySelector("pre code")?.textContent).toContain("MATCH (p:Paper)");
    expect(container.querySelector("pre.kc-tool-result")?.textContent).toContain("2024");
    // the query is not repeated as input JSON
    expect(container.querySelectorAll("pre")).toHaveLength(2);
  });

  it("other tools show their input as pretty JSON without the description", () => {
    const { container } = render(<ToolCall step={{ tool: "semantic_search", description: "Find", input: { query: "diffusion", limit: 5, description: "Find" }, result: "[]" }} onPaper={noop} />);
    expect(screen.getByText("Search")).toBeInTheDocument();
    expect(screen.getByText("“diffusion”")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button"));
    const input = container.querySelector("pre.kc-tool-input")!;
    expect(input.textContent).toBe(JSON.stringify({ query: "diffusion", limit: 5 }, null, 2));
  });

  it("paper chips open the preview, figure thumbnails open the figure, web links open in a new tab", () => {
    const onPaper = vi.fn(), onFigure = vi.fn();
    render(<ToolCall onPaper={onPaper} onFigure={onFigure} step={{
      tool: "list_figures", description: "Figures of AF3", papers: [{ id: "p1", title: "AlphaFold 3", year: 2024 }],
      figures: [{ image_url: "/papers/p1/figures/f1/image", caption: "Overview", figure_number: 1 }],
      links: ["https://www.nature.com/x", "javascript:alert(1)"],
    }} />);
    fireEvent.click(screen.getByRole("button", { name: /Figures/ }));
    fireEvent.click(screen.getByText("AlphaFold 3 · 2024"));
    expect(onPaper).toHaveBeenCalledWith({ id: "p1", title: "AlphaFold 3", year: 2024 });
    const img = screen.getByAltText("Overview");
    expect(img).toHaveAttribute("src", "http://api/papers/p1/figures/f1/image");
    fireEvent.click(img);
    expect(onFigure).toHaveBeenCalledWith("http://api/papers/p1/figures/f1/image", "Overview");
    const web = screen.getByText("nature.com").closest("a")!;
    expect(web).toHaveAttribute("target", "_blank");
    expect(screen.queryByText(/javascript/)).toBeNull();
  });

  it("marks an error and shows its message", () => {
    const { container } = render(<ToolCall step={{ tool: "run_cypher", description: "Bad", cypher: "MATCH", result: "SyntaxError", is_error: true }} onPaper={noop} />);
    expect(container.querySelector(".kc-tool")).toHaveClass("error");
    fireEvent.click(screen.getByRole("button"));
    expect(container.querySelector("pre.kc-tool-result")).toHaveClass("error");
  });

  it("an old step without the new fields is as informative as before", () => {
    const { container } = render(<ToolCall onPaper={noop} step={{
      kind: "search", description: "Find diffusion papers", cypher: "[vector search] diffusion", count: 3, papers: [{ id: "p1", title: "DDPM", year: 2020 }],
    }} />);
    expect(screen.getByText("Search")).toBeInTheDocument();
    expect(screen.getByText("Find diffusion papers")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("DDPM · 2020")).toBeInTheDocument();
    expect(container.querySelector("pre")).toBeNull(); // the vector-search marker is not a query to show
  });

  it("an old Cypher step shows its query, a step without detail does not expand", () => {
    const { container, rerender } = render(<ToolCall onPaper={noop} step={{ kind: "cypher", description: "Papers in project X", cypher: "MATCH (p) RETURN p" }} />);
    fireEvent.click(screen.getByRole("button"));
    expect(container.querySelector("pre code")?.textContent).toBe("MATCH (p) RETURN p");
    rerender(<ToolCall onPaper={noop} step={{ description: "Searching the web", kind: "web" }} />);
    expect(screen.getByText("Web")).toBeInTheDocument();
    expect(screen.queryByText("▸")).toBeNull();
  });

  it("shows a spinner while pending", () => {
    render(<ToolCall onPaper={noop} step={{ description: "Find", tool: "semantic_search" }} pending />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

describe("Trace", () => {
  const steps: TraceStep[] = [
    { kind: "text", description: "", text: "Let me look at $x^2$ first." },
    { tool: "semantic_search", description: "Find", input: { query: "a" } },
    { tool: "load_full_text", description: "Read it", papers: [{ id: "p1", title: "AF3" }] },
  ];

  it("renders text steps as prose (maths rendered), not as tool rows, and every tool call in order", () => {
    const { container } = render(<Trace steps={steps} onPaper={noop} />);
    expect(container.querySelectorAll(".kc-tool")).toHaveLength(2);
    expect(container.querySelector(".kc-trace-text .katex")).not.toBeNull();
    expect(container.querySelector(".kc-trace-text")?.textContent).toContain("Let me look at");
    expect([...container.querySelectorAll(".kc-tool-name")].map((e) => e.textContent)).toEqual(["Search", "Read"]);
  });

  it("spins only the last tool row while waiting for the answer", () => {
    const { container, rerender } = render(<Trace steps={steps} waiting onPaper={noop} />);
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(container.querySelectorAll(".kc-tool")[1].querySelector(".kc-spinner")).not.toBeNull();
    rerender(<Trace steps={steps} onPaper={noop} />);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("renders nothing without steps or with only blank text steps", () => {
    const { container } = render(<Trace steps={[{ kind: "text", description: "", text: "  " }]} onPaper={noop} />);
    expect(container).toBeEmptyDOMElement();
  });
});
