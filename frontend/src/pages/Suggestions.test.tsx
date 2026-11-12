import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as insights from "../api/insights";
import type { SuggestionOut } from "../api/insights";
import Suggestions from "./Suggestions";

vi.mock("../api/insights");
const auth = vi.hoisted(() => ({ useAuth: vi.fn() }));
vi.mock("../contexts/AuthContext", () => auth);

function sug(over: Partial<SuggestionOut> = {}): SuggestionOut {
  return {
    id: "s1",
    text: "Export a project's notes as one Markdown file",
    detail: null,
    source: "user",
    status: "open",
    created_by: "niklas",
    created_at: "2026-11-10T09:00:00+00:00",
    updated_at: "2026-11-10T09:00:00+00:00",
    votes: 2,
    voted: false,
    context: null,
    conversation_id: null,
    seen: 1,
    ...over,
  };
}

function renderPage() {
  return render(<MemoryRouter><Suggestions /></MemoryRouter>);
}

describe("Suggestions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.useAuth.mockReturnValue({ username: "niklas", isAdmin: false });
    vi.mocked(insights.listSuggestions).mockResolvedValue([sug()]);
    vi.mocked(insights.getSuggestionCounts).mockResolvedValue({ open: 1, planned: 2, done: 3, dismissed: 0 });
  });

  it("renders suggestions, status tabs with counts and requests the open tab by votes", async () => {
    renderPage();
    expect(await screen.findByText("Export a project's notes as one Markdown file")).toBeInTheDocument();
    expect(insights.listSuggestions).toHaveBeenCalledWith({ status: "open", sort: "votes" });
    const tablist = screen.getByRole("tablist", { name: "Status" });
    await waitFor(() => expect(within(tablist).getByRole("tab", { name: /Planned\s*2/ })).toBeInTheDocument());
    expect(within(tablist).getByRole("tab", { name: /All\s*6/ })).toBeInTheDocument();
    expect(within(tablist).getByRole("tab", { name: /Open/ })).toHaveAttribute("aria-selected", "true");
  });

  it("switches tab and sort", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/Export a project/);
    await user.click(screen.getByRole("tab", { name: /Done/ }));
    await waitFor(() => expect(insights.listSuggestions).toHaveBeenLastCalledWith({ status: "done", sort: "votes" }));
    await user.selectOptions(screen.getByLabelText("Sort"), "new");
    await waitFor(() => expect(insights.listSuggestions).toHaveBeenLastCalledWith({ status: "done", sort: "new" }));
    await user.click(screen.getByRole("tab", { name: /All/ }));
    await waitFor(() => expect(insights.listSuggestions).toHaveBeenLastCalledWith({ status: undefined, sort: "new" }));
  });

  it("says what will appear in an empty tab", async () => {
    vi.mocked(insights.listSuggestions).mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText("Nothing here yet")).toBeInTheDocument();
    expect(screen.getByText(/have not been picked up yet will appear here/)).toBeInTheDocument();
  });

  it("shows source, seen count, context excerpt and collapsible detail for chat suggestions", async () => {
    const user = userEvent.setup();
    vi.mocked(insights.listSuggestions).mockResolvedValue([
      sug({ source: "chat", seen: 3, context: "Can I export my notes?", detail: "Long detail text", created_by: "anna" }),
    ]);
    renderPage();
    expect(await screen.findByText("from chat")).toBeInTheDocument();
    expect(screen.getByText(/seen 3/)).toBeInTheDocument();
    expect(screen.getByText(/Can I export my notes\?/)).toBeInTheDocument();
    expect(screen.queryByText("Long detail text")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show details" }));
    expect(screen.getByText("Long detail text")).toBeInTheDocument();
  });

  it("votes optimistically and keeps the server's answer", async () => {
    const user = userEvent.setup();
    let resolve!: (s: SuggestionOut) => void;
    vi.mocked(insights.voteSuggestion).mockReturnValue(new Promise((r) => { resolve = r; }));
    renderPage();
    const btn = await screen.findByRole("button", { name: /Vote for/ });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    await user.click(btn);
    const pressed = screen.getByRole("button", { name: /Remove your vote/ });
    expect(pressed).toHaveAttribute("aria-pressed", "true");
    expect(pressed).toHaveTextContent("3");
    resolve(sug({ voted: true, votes: 3 }));
    await waitFor(() => expect(insights.voteSuggestion).toHaveBeenCalledWith("s1"));
    expect(screen.getByRole("button", { name: /Remove your vote/ })).toHaveTextContent("3");
  });

  it("rolls the vote back when the request fails", async () => {
    const user = userEvent.setup();
    vi.mocked(insights.voteSuggestion).mockRejectedValue(new Error("nope"));
    renderPage();
    await user.click(await screen.findByRole("button", { name: /Vote for/ }));
    const btn = await screen.findByRole("button", { name: /Vote for/ });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    expect(btn).toHaveTextContent("2");
    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
  });

  it("validates the text length and submits the new suggestion", async () => {
    const user = userEvent.setup();
    vi.mocked(insights.createSuggestion).mockResolvedValue(sug({ id: "s2", text: "Dark mode" }));
    renderPage();
    await screen.findByText(/Export a project/);
    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Suggestion"), "ab");
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Suggestion"), "c");
    expect(screen.getByText(/3 \/ 280/)).toBeInTheDocument();
    expect(submit).toBeEnabled();
    await user.clear(screen.getByLabelText("Suggestion"));
    await user.type(screen.getByLabelText("Suggestion"), "Dark mode");
    await user.type(screen.getByLabelText(/Details/), "Easier on the eyes");
    await user.click(submit);
    await waitFor(() => expect(insights.createSuggestion).toHaveBeenCalledWith({ text: "Dark mode", detail: "Easier on the eyes" }));
    await waitFor(() => expect(screen.getByLabelText("Suggestion")).toHaveValue(""));
    expect(insights.listSuggestions).toHaveBeenCalledTimes(2);
  });

  it("shows the status select and delete only to those allowed", async () => {
    vi.mocked(insights.listSuggestions).mockResolvedValue([sug({ created_by: "anna" })]);
    renderPage();
    await screen.findByText(/Export a project/);
    expect(screen.queryByRole("combobox", { name: /Status of/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("lets the author delete after confirming", async () => {
    const user = userEvent.setup();
    vi.mocked(insights.deleteSuggestion).mockResolvedValue(undefined);
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    expect(insights.deleteSuggestion).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Yes, delete" }));
    await waitFor(() => expect(insights.deleteSuggestion).toHaveBeenCalledWith("s1"));
    await waitFor(() => expect(screen.queryByText(/Export a project/)).not.toBeInTheDocument());
  });

  it("lets an admin change the status, which moves the row out of the open tab", async () => {
    const user = userEvent.setup();
    auth.useAuth.mockReturnValue({ username: "root", isAdmin: true });
    vi.mocked(insights.updateSuggestion).mockResolvedValue(sug({ status: "planned" }));
    renderPage();
    await user.selectOptions(await screen.findByRole("combobox", { name: /Status of/ }), "planned");
    await waitFor(() => expect(insights.updateSuggestion).toHaveBeenCalledWith("s1", { status: "planned" }));
    await waitFor(() => expect(screen.queryByText(/Export a project/)).not.toBeInTheDocument());
  });

  it("shows a load error", async () => {
    vi.mocked(insights.listSuggestions).mockRejectedValue(new Error("down"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("down");
  });
});
