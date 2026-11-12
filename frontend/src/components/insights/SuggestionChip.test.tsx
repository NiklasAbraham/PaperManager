import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as insights from "../../api/insights";
import type { SuggestionOut } from "../../api/insights";
import SuggestionChip, { isSuggestionChipDismissed } from "./SuggestionChip";

vi.mock("../../api/insights");

const KEY = "pm_dismissed_suggestion_chips";

function suggestion(over: Partial<SuggestionOut> = {}): SuggestionOut {
  return {
    id: "s1",
    text: "Let me export the knowledge graph as GraphML",
    detail: null,
    source: "chat",
    status: "open",
    created_by: "niklas",
    created_at: "2026-11-12T09:00:00+00:00",
    updated_at: "2026-11-12T09:00:00+00:00",
    votes: 1,
    voted: false,
    context: null,
    conversation_id: null,
    seen: 1,
    ...over,
  };
}

function renderChip(s = suggestion(), onDismiss?: (id: string) => void) {
  return render(
    <MemoryRouter>
      <SuggestionChip suggestion={s} onDismiss={onDismiss} />
    </MemoryRouter>,
  );
}

describe("SuggestionChip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("shows the suggestion, its full text as a title and a link to the list", () => {
    renderChip();
    expect(screen.getByText("Suggestion:")).toBeInTheDocument();
    expect(screen.getByTitle("Let me export the knowledge graph as GraphML")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All suggestions" })).toHaveAttribute("href", "/suggestions");
  });

  it("votes and shows the server's answer", async () => {
    vi.mocked(insights.voteSuggestion).mockResolvedValue(suggestion({ votes: 2, voted: true }));
    const user = userEvent.setup();
    renderChip();
    const btn = screen.getByRole("button", { name: /vote for this suggestion/i });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    await user.click(btn);
    expect(insights.voteSuggestion).toHaveBeenCalledWith("s1");
    await waitFor(() => expect(screen.getByRole("button", { name: /remove your vote/i })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("button", { name: /remove your vote/i })).toHaveTextContent("Voted 2");
  });

  it("rolls the vote back when the request fails", async () => {
    vi.mocked(insights.voteSuggestion).mockRejectedValue(new Error("API 500"));
    const user = userEvent.setup();
    renderChip();
    await user.click(screen.getByRole("button", { name: /vote for this suggestion/i }));
    await waitFor(() => expect(screen.getByRole("button", { name: /vote for this suggestion/i })).toHaveAttribute("aria-pressed", "false"));
    expect(screen.getByRole("button", { name: /vote for this suggestion/i })).toHaveTextContent("+1 1");
  });

  it("hides on dismiss, remembers the id and tells the parent", async () => {
    const onDismiss = vi.fn();
    const user = userEvent.setup();
    const { unmount } = renderChip(suggestion(), onDismiss);
    await user.click(screen.getByRole("button", { name: "Dismiss suggestion" }));
    expect(screen.queryByText("Suggestion:")).not.toBeInTheDocument();
    expect(onDismiss).toHaveBeenCalledWith("s1");
    expect(JSON.parse(localStorage.getItem(KEY) ?? "[]")).toEqual(["s1"]);
    expect(isSuggestionChipDismissed("s1")).toBe(true);
    expect(isSuggestionChipDismissed("s2")).toBe(false);
    unmount();

    // A new mount for the same suggestion renders nothing.
    const { container } = renderChip();
    expect(container).toBeEmptyDOMElement();
  });

  it("keeps at most 200 remembered ids, newest last", async () => {
    localStorage.setItem(KEY, JSON.stringify(Array.from({ length: 200 }, (_, i) => `old${i}`)));
    const user = userEvent.setup();
    renderChip(suggestion({ id: "fresh" }));
    await user.click(screen.getByRole("button", { name: "Dismiss suggestion" }));
    const ids = JSON.parse(localStorage.getItem(KEY) ?? "[]") as string[];
    expect(ids).toHaveLength(200);
    expect(ids[0]).toBe("old1");
    expect(ids[199]).toBe("fresh");
  });

  it("survives broken storage content", () => {
    localStorage.setItem(KEY, "{not json");
    expect(isSuggestionChipDismissed("s1")).toBe(false);
    renderChip();
    expect(screen.getByText("Suggestion:")).toBeInTheDocument();
  });
});
