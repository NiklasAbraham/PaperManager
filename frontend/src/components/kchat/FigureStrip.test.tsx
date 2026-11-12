import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchFigures } from "../../api/client";
import type { Figure } from "../../types";
import { FigureStrip } from "./FigureStrip";
import { ChatLinksContext, Markdown } from "./Markdown";

vi.mock("../../api/client", async (orig) => ({ ...(await orig<typeof import("../../api/client")>()), fetchFigures: vi.fn() }));

const ID = "c7d9ec3d-0df1-4c18-970f-7f6dc34e5e3e";
const PID = "0a1b2c3d-0df1-4c18-970f-7f6dc34e5e3e";
const img = (n: number, alt = `Figure ${n}: part ${n} of the model`) => `![${alt}](/papers/${ID}/figures/f${n}/image)`;
const fig = (n: number, extra: Partial<Figure> = {}): Figure => ({
  id: `fig${n}`, paper_id: PID, figure_number: n, caption: `caption ${n}`, drive_file_id: `d${n}`, drive_url: null, page_number: n, created_at: "", ...extra,
});

beforeEach(() => { vi.mocked(fetchFigures).mockReset(); });

describe("Markdown: strips", () => {
  it("renders three images in a row as one strip with short labels", () => {
    const { container } = render(<Markdown text={`${img(1)}\n${img(2)}\n${img(3)}`} />);
    expect(container.querySelectorAll(".kc-strip")).toHaveLength(1);
    expect(container.querySelectorAll(".kc-strip-thumb")).toHaveLength(3);
    expect(container.querySelectorAll(".kc-figure")).toHaveLength(0);
    expect(Array.from(container.querySelectorAll(".kc-strip-label")).map((e) => e.textContent)).toEqual(["1: part 1", "2: part 2", "3: part 3"]);
  });

  it("renders two images as two figures and no strip", () => {
    const { container } = render(<Markdown text={`${img(1)}\n\n${img(2)}`} />);
    expect(container.querySelectorAll(".kc-figure")).toHaveLength(2);
    expect(container.querySelector(".kc-strip")).toBeNull();
  });

  it("shows a refused image in a strip as a note tile", () => {
    const { container } = render(<Markdown text={`${img(1)}\n${img(2)}\n![x](/auth/me)`} />);
    expect(container.querySelectorAll(".kc-strip-thumb")).toHaveLength(2);
    expect(screen.getByText("figure not shown")).toBeInTheDocument();
  });

  it("opens a strip image in a lightbox, steps with the arrow keys and closes with Escape", () => {
    render(<Markdown text={`${img(1)}\n${img(2)}\n${img(3)}`} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Figure 2: part 2 of the model" }));
    const dlg = screen.getByRole("dialog");
    expect(within(dlg).getByText("2 / 3")).toBeInTheDocument();
    expect(within(dlg).getByRole("img").getAttribute("src")).toContain("/figures/f2/image");
    const scroll = document.body.style.overflow;
    expect(scroll).toBe("hidden");

    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(within(dlg).getByText("3 / 3")).toBeInTheDocument();
    expect(within(dlg).getByRole("img").getAttribute("src")).toContain("/figures/f3/image");
    expect(within(dlg).getByLabelText("Next figure")).toBeDisabled();
    fireEvent.keyDown(document, { key: "ArrowLeft" });
    fireEvent.click(within(dlg).getByLabelText("Previous figure"));
    expect(within(dlg).getByText("1 / 3")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes on a click on the backdrop but not on the picture", () => {
    render(<Markdown text={`${img(1)}\n${img(2)}\n${img(3)}`} />);
    fireEvent.click(screen.getByRole("button", { name: "Figure 1: part 1 of the model" }));
    fireEvent.click(screen.getByRole("dialog").querySelector("img")!);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("dialog"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers 'beside the chat' only with a ChatLinksContext, and it opens the figure there", () => {
    const text = `${img(1)}\n${img(2)}\n${img(3)}`;
    const first = render(<Markdown text={text} />);
    fireEvent.click(screen.getByRole("button", { name: "Figure 1: part 1 of the model" }));
    expect(screen.queryByText("beside the chat")).toBeNull();
    first.unmount();

    const links = { openPaper: vi.fn(), openFigure: vi.fn() };
    render(<ChatLinksContext.Provider value={links}><Markdown text={text} /></ChatLinksContext.Provider>);
    fireEvent.click(screen.getByRole("button", { name: "Figure 2: part 2 of the model" }));
    fireEvent.click(screen.getByText("beside the chat"));
    expect(links.openFigure).toHaveBeenCalledWith(expect.stringContaining("/figures/f2/image"), "Figure 2: part 2 of the model");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Markdown: all figures of a paper", () => {
  it("fetches the figures and renders them as a strip titled by the alt text", async () => {
    vi.mocked(fetchFigures).mockResolvedValue([fig(1), fig(2, { figure_number: "S1" }), fig(3, { drive_file_id: "" })]);
    const { container } = render(<Markdown text={`![All figures of the paper](/papers/${PID}/figures/*)`} />);
    expect(screen.getByText(/loading/)).toBeInTheDocument();
    await waitFor(() => expect(container.querySelectorAll(".kc-strip-thumb")).toHaveLength(2));
    expect(fetchFigures).toHaveBeenCalledWith(PID);
    expect(screen.getByText("All figures of the paper")).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll(".kc-strip-label")).map((e) => e.textContent)).toEqual(["Fig. 1", "Fig. S1"]);
    expect(container.querySelector(".kc-strip-thumb img")!.getAttribute("src")).toContain(`/papers/${PID}/figures/fig1/image`);
  });

  it("says so when the paper has no figures", async () => {
    const id = "11111111-0df1-4c18-970f-7f6dc34e5e3e";
    vi.mocked(fetchFigures).mockResolvedValue([]);
    render(<Markdown text={`![Figures](/papers/${id}/figures/*)`} />);
    expect(await screen.findByText(/no figures extracted/)).toBeInTheDocument();
  });

  it("says so when the request fails", async () => {
    const id = "22222222-0df1-4c18-970f-7f6dc34e5e3e";
    vi.mocked(fetchFigures).mockImplementation(() => Promise.reject(new Error("HTTP 404")));
    render(<Markdown text={`![Figures](/papers/${id}/figures/*)`} />);
    expect(await screen.findByText(/not available \(HTTP 404\)/)).toBeInTheDocument();
  });
});

describe("FigureStrip", () => {
  it("swaps a thumbnail that fails to load for a note", () => {
    const items = [1, 2, 3].map((n) => ({ src: `https://example.org/${n}.png`, url: `https://example.org/${n}.png`, alt: `a${n}` }));
    const { container } = render(<FigureStrip items={items} />);
    fireEvent.error(container.querySelectorAll(".kc-strip-thumb img")[1]);
    expect(screen.getByText("figure not shown")).toBeInTheDocument();
    expect(container.querySelectorAll(".kc-strip-thumb")).toHaveLength(2);
  });

  it("keeps Tab inside the open lightbox", () => {
    const items = [1, 2, 3].map((n) => ({ src: `https://example.org/${n}.png`, url: `https://example.org/${n}.png`, alt: `a${n}` }));
    render(<FigureStrip items={items} />);
    fireEvent.click(screen.getAllByRole("button")[0]);
    const dlg = screen.getByRole("dialog");
    expect(dlg.contains(document.activeElement)).toBe(true);
    const buttons = within(dlg).getAllByRole("button").filter((b) => !(b as HTMLButtonElement).disabled);
    act(() => buttons[buttons.length - 1].focus());
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(buttons[0]);
  });
});
