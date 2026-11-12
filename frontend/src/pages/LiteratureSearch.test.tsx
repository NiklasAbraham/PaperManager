import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import LiteratureSearch from "./LiteratureSearch";

vi.mock("../components/literature/ExternalSearch", () => ({ default: () => <div>external-search</div> }));
vi.mock("../components/literature/KeywordFeed", () => ({ default: () => <div>keyword-feed</div> }));

function Where() {
  return <div data-testid="where">{useLocation().search}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LiteratureSearch />
      <Where />
    </MemoryRouter>
  );
}

describe("LiteratureSearch (Find papers)", () => {
  it("defaults to the Feed tab", () => {
    renderAt("/literature");
    expect(screen.getByText("keyword-feed")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Feed" })).toHaveAttribute("aria-selected", "true");
  });

  it("opens the Search tab from ?tab=search and puts the tab in the URL", async () => {
    const user = userEvent.setup();
    renderAt("/literature?tab=search");
    expect(screen.getByText("external-search")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Feed" }));
    expect(screen.getByText("keyword-feed")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("?tab=feed");
  });
});
