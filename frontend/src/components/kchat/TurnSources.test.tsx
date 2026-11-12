import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { answerSources, type AnswerSources } from "./sources";
import { TurnSources } from "./TurnSources";

const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

describe("TurnSources", () => {
  it("renders paper chips as real links that open the preview on a plain click", () => {
    const onPaper = vi.fn();
    const sources: AnswerSources = {
      papers: [{ id: id(1), title: "AlphaFold 3", year: 2024, verbs: ["cited", "read"], rank: 0 }, { id: id(2), title: "DDPM", verbs: ["found"], rank: 3 }],
      web: [], searches: [],
    };
    render(<TurnSources sources={sources} onPaper={onPaper} />);
    expect(screen.getByText("Sources")).toBeInTheDocument();
    const a = screen.getByText("AlphaFold 3").closest("a")!;
    expect(a.getAttribute("href")).toBe(`/paper/${id(1)}`);
    expect(a).toHaveAttribute("title", "cited, read");
    expect(a).toHaveClass("strong");
    expect(screen.getByText("DDPM").closest("a")).toHaveClass("weak");
    expect(fireEvent.click(a)).toBe(false); // default prevented: the preview pane opens instead
    expect(onPaper).toHaveBeenCalledWith({ id: id(1), title: "AlphaFold 3", year: 2024 });
  });

  it("lets ctrl/meta clicks follow the link", () => {
    const onPaper = vi.fn();
    render(<TurnSources sources={answerSources(null, `[X](/paper/${id(1)})`)} onPaper={onPaper} />);
    const a = screen.getByText("X").closest("a")!;
    expect(fireEvent.click(a, { ctrlKey: true })).toBe(true);
    expect(fireEvent.click(a, { metaKey: true })).toBe(true);
    expect(onPaper).not.toHaveBeenCalled();
  });

  it("shows ten chips and a +N toggle for the rest", () => {
    const papers = Array.from({ length: 13 }, (_, i) => ({ id: id(i), title: `Paper ${i}`, verbs: ["found" as const], rank: 3 }));
    render(<TurnSources sources={{ papers, web: [], searches: [] }} onPaper={() => {}} />);
    expect(screen.queryByText("Paper 10")).toBeNull();
    fireEvent.click(screen.getByText("+3"));
    expect(screen.getByText("Paper 12")).toBeInTheDocument();
    fireEvent.click(screen.getByText("fewer"));
    expect(screen.queryByText("Paper 12")).toBeNull();
  });

  it("shows web chips in a new tab and the number of searches with a tooltip", () => {
    render(<TurnSources sources={{
      papers: [], web: [{ url: "https://arxiv.org/abs/1", label: "arxiv.org" }], searches: ["“diffusion”", "Count papers"],
    }} onPaper={() => {}} />);
    const w = screen.getByText("arxiv.org").closest("a")!;
    expect(w).toHaveAttribute("target", "_blank");
    expect(w.getAttribute("rel")).toContain("noreferrer");
    expect(screen.getByText("2 searches")).toHaveAttribute("title", "“diffusion”\nCount papers");
  });

  it("uses the singular for one search and renders nothing without sources", () => {
    const { container, rerender } = render(<TurnSources sources={{ papers: [], web: [], searches: ["q"] }} onPaper={() => {}} />);
    expect(screen.getByText("1 search")).toBeInTheDocument();
    rerender(<TurnSources sources={{ papers: [], web: [], searches: [] }} onPaper={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
});
