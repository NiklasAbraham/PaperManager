import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AnimSpec, GraphSpec, TextSpec } from "../../types";
import ConceptCard, { tidyCaption } from "./ConceptCard";

// jsdom has no ResizeObserver; the graph view only needs it to exist.
globalThis.ResizeObserver ??= class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;

const anim: AnimSpec = { type: "2d-anim", title: "Sampler", caption: "Noise to data.", setup_code: "return { draw: function () {} };" };

describe("ConceptCard", () => {
  it("shows a formula walk-through with its kind, title and caption", () => {
    render(<ConceptCard spec={{ type: "formula", title: "Loss", caption: "Weighted MSE.", main_latex: "L=\\|x\\|^2",
      steps: [{ latex: "a", explanation: "first step" }] }} footnote="made from this answer" />);
    expect(screen.getByText("formula")).toBeInTheDocument();
    expect(screen.getByText("Loss")).toBeInTheDocument();
    expect(screen.getByText("first step")).toBeInTheDocument();
    expect(screen.getByText("Weighted MSE.")).toBeInTheDocument();
    expect(screen.getByText("made from this answer")).toBeInTheDocument();
  });

  it("falls back to the label when the spec has no title", () => {
    render(<ConceptCard spec={{ ...anim, title: "" }} label="From the label" />);
    expect(screen.getByText("From the label")).toBeInTheDocument();
  });

  it("renders a sourced note with its citations", () => {
    const spec: TextSpec = { type: "2d-text", title: "Background", caption: "", body_markdown: "Some **context**.",
      citations: [{ label: "Ho et al.", source: "NeurIPS", url: "https://arxiv.org/abs/2006.11239" }] };
    render(<ConceptCard spec={spec} />);
    expect(screen.getByText("background")).toBeInTheDocument();
    expect(screen.getByText("Ho et al.")).toBeInTheDocument();
    expect(screen.getByText("arxiv.org")).toBeInTheDocument();
  });

  it("runs an animation sandboxed with pause, speeds and replay", () => {
    const { container } = render(<ConceptCard spec={anim} />);
    const frame = container.querySelector("iframe")!;
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    const post = vi.spyOn(frame.contentWindow!, "postMessage");
    const on = (name: string) => screen.getByText(name).className.includes("on");

    expect(on("0.5×")).toBe(true);
    fireEvent.click(screen.getByText("❚❚ pause"));
    expect(screen.getByText("▶ play")).toBeInTheDocument();
    expect(on("0.5×")).toBe(false);
    expect(post).toHaveBeenCalledWith({ type: "concept-anim-speed", speed: 0 }, "*");

    fireEvent.click(screen.getByText("2×"));
    expect(on("2×")).toBe(true);
    expect(screen.getByText("❚❚ pause")).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith({ type: "concept-anim-speed", speed: 2 }, "*");

    fireEvent.click(screen.getByText("↻ replay"));
    expect(container.querySelector("iframe")).not.toBe(frame);   // a fresh run
  });

  it("reports an animation crash from the sandbox and shows it", () => {
    const onErr = vi.fn();
    const { container } = render(<ConceptCard spec={anim} onRuntimeError={onErr} />);
    const frame = container.querySelector("iframe")!;
    act(() => {
      window.dispatchEvent(new MessageEvent("message", { source: frame.contentWindow, data: { type: "concept-anim-error", message: "Animation crashed mid-frame: x is undefined" } }));
    });
    expect(onErr).toHaveBeenCalledWith("Animation crashed mid-frame: x is undefined");
    expect(screen.getByText(/x is undefined/)).toBeInTheDocument();
  });

  it("reports bad graph data instead of drawing", () => {
    const onErr = vi.fn();
    const spec: GraphSpec = { type: "graph", title: "G", caption: "", chart_type: "lines", x_label: "x", y_label: "y", data_json: "{oops" };
    render(<ConceptCard spec={spec} onRuntimeError={onErr} />);
    expect(onErr).toHaveBeenCalledWith(expect.stringContaining("Could not parse graph data_json"));
  });

  it("shows extra header actions", () => {
    const fix = vi.fn();
    render(<ConceptCard spec={anim} actions={<button onClick={fix}>fix</button>} />);
    fireEvent.click(screen.getByText("fix"));
    expect(fix).toHaveBeenCalled();
  });
});

describe("tidyCaption", () => {
  it("ends a cut caption at its last whole sentence", () => {
    expect(tidyCaption("One point here. Another point. A third that was cut mid wo")).toBe("One point here. Another point.");
    expect(tidyCaption("Complete sentence.")).toBe("Complete sentence.");
    expect(tidyCaption("no sentence end at all")).toBe("no sentence end at all…");
    expect(tidyCaption("")).toBe("");
  });
});
