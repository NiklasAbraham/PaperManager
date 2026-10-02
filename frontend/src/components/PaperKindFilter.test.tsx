import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import PaperKindFilter from "./PaperKindFilter";
import { isVisible } from "../lib/paperKinds";

const papers = [
  { document_type: "paper", has_pdf: true },
  { document_type: "paper", has_pdf: false },
  { document_type: "news_article", has_pdf: false },
  {},
];

describe("isVisible", () => {
  it("treats a missing document_type as a paper without PDF", () => {
    expect(isVisible({}, new Set(["paper"]))).toBe(false);
    expect(isVisible({}, new Set(["no_pdf"]))).toBe(false);
    expect(isVisible({}, new Set(["news_article", "pdf"]))).toBe(true);
  });

  it("hides a paper when either its type or its PDF state is hidden", () => {
    expect(isVisible({ document_type: "news_article", has_pdf: false }, new Set(["news_article"]))).toBe(false);
    expect(isVisible({ document_type: "paper", has_pdf: true }, new Set(["no_pdf"]))).toBe(true);
  });
});

describe("PaperKindFilter", () => {
  it("shows counts only for kinds that occur and toggles on click", async () => {
    const onToggle = vi.fn();
    render(<PaperKindFilter papers={papers} hidden={new Set()} onToggle={onToggle} onReset={() => {}} />);

    expect(screen.getByRole("button", { name: /Papers 3/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /News articles 1/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Books/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Metadata only 3/ })).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: /News articles/ }));
    expect(onToggle).toHaveBeenCalledWith("news_article");
  });

  it("offers Show all when something is hidden", async () => {
    const onReset = vi.fn();
    render(<PaperKindFilter papers={papers} hidden={new Set(["no_pdf"])} onToggle={() => {}} onReset={onReset} />);

    expect(screen.getByText(/Showing 1 of 4/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Show all" }));
    expect(onReset).toHaveBeenCalled();
  });
});
