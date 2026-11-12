import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { KnowledgeMessage, SseEvent } from "../types";

const api = vi.hoisted(() => ({
  streamKnowledgeChat: vi.fn(),
  stopKnowledgeChat: vi.fn(async () => ({ stopped: true })),
  listConversations: vi.fn(async () => [] as unknown[]),
  getConversationMessages: vi.fn(async () => [] as unknown[]),
  visualiseAnswer: vi.fn(async () => ({ status: "running", error: null, concepts: null })),
  getAnswerConcepts: vi.fn(),
  forkConversation: vi.fn(),
  renameConversation: vi.fn(), deleteConversation: vi.fn(), compactConversation: vi.fn(), repairAnswerConcept: vi.fn(),
  apiFetch: vi.fn(async () => []),
  apiUrl: (p: string) => `http://api${p}`,
}));
vi.mock("../api/client", () => api);
vi.mock("../contexts/SettingsContext", () => ({
  useAppSettings: () => ({ settings: { knowledgeChatDefaultModel: "claude", knowledgeChatUseWeb: false } }),
}));
vi.mock("../lib/chatModels", () => ({
  CHAT_MODEL_LABELS: { claude: "Claude", "claude-code": "Claude Code", "claude-work": "Claude (Work)", litellm: "LiteLLM" },
  useChatModels: () => ["claude"],
}));

import KnowledgeChat, { awaitSavedAnswer, toItems } from "./KnowledgeChat";

globalThis.ResizeObserver ??= class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;
Element.prototype.scrollTo ??= () => {};
Element.prototype.scrollIntoView ??= () => {};

const msg = (id: string, role: KnowledgeMessage["role"], content: string, extra: Partial<KnowledgeMessage> = {}): KnowledgeMessage =>
  ({ id, role, content, created_at: id, paper_refs: [], ...extra });

async function* events(list: SseEvent[], fail?: Error) {
  for (const e of list) yield e;
  if (fail) throw fail;
}

const ask = (text: string) => {
  const box = screen.getByLabelText("Question");
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
};

const ANSWER = "## Objective\nThe loss is $\\|x\\|^2$, see [AlphaFold 3](/paper/c7d9ec3d-0df1-4c18-970f-7f6dc34e5e3e).";

beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });

describe("KnowledgeChat page", () => {
  it("shows the welcome with starters that fill the composer", () => {
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    expect(screen.getByText("Ask your library anything.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Explain the maths"));
    expect((screen.getByLabelText("Question") as HTMLTextAreaElement).value).toMatch(/score-matching/);
  });

  it("streams an answer with its steps, citation chips and context, then offers Visualise", async () => {
    api.streamKnowledgeChat.mockReturnValue(events([
      { type: "step", kind: "search", description: "Find diffusion papers", count: 3, papers: [{ id: "p1", title: "DDPM" }] },
      { type: "context", papers: [{ id: "p1", title: "DDPM", tokens: 100, color: "#000" }],
        token_totals: { system: 10, papers: 100, history: 0, question: 5, total: 115, limit: 200000 } },
      { type: "conversation", conversation_id: "c1", user_message_id: "u1" },
      { type: "token", text: ANSWER.slice(0, 20) },
      { type: "token", text: ANSWER.slice(20) },
      { type: "done", conversation_id: "c1", message_id: "a1" },
    ]));
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    ask("Explain the loss");
    expect(await screen.findByText("✦ Visualise")).toBeInTheDocument();
    expect(screen.getByText("Explain the loss")).toHaveClass("user-text");
    expect(screen.getByText("Find diffusion papers")).toBeInTheDocument();
    expect(document.querySelectorAll(".kc-cite")).toHaveLength(1);
    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByText("1 search")).toBeInTheDocument();
    expect(screen.getByText("1 in context ▸")).toBeInTheDocument();
    expect(api.streamKnowledgeChat.mock.calls[0][0]).toMatchObject({ question: "Explain the loss", history: [], use_web: false, paper_ids: [] });

    fireEvent.click(screen.getByText("✦ Visualise"));
    expect(api.visualiseAnswer).toHaveBeenCalledWith("a1");
    expect(await screen.findByText(/Making concept cards from this answer/)).toBeInTheDocument();
  });

  it("opens a cited paper in the preview pane", async () => {
    api.streamKnowledgeChat.mockReturnValue(events([{ type: "token", text: ANSWER }, { type: "done", conversation_id: "c1", message_id: "a1" }]));
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    ask("q");
    fireEvent.click(await screen.findByText("AlphaFold 3", { selector: "a" }));
    expect(await screen.findByLabelText("Preview")).toBeInTheDocument();
    expect(api.apiFetch).toHaveBeenCalledWith("/papers/c7d9ec3d-0df1-4c18-970f-7f6dc34e5e3e");
  });

  it("recovers the saved answer after the connection drops mid-answer", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.streamKnowledgeChat.mockReturnValue(events([
      { type: "conversation", conversation_id: "c1", user_message_id: "u1" },
      { type: "token", text: "partial" },
    ], new TypeError("network error")));
    api.getConversationMessages
      .mockResolvedValueOnce([msg("u1", "user", "q")])          // first poll: still being written
      .mockResolvedValue([msg("u1", "user", "q"), msg("a1", "assistant", "The whole saved answer.")]);
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    ask("q");
    expect(await screen.findByText(/connection lost/)).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(await screen.findByText("The whole saved answer.")).toBeInTheDocument();
    expect(screen.queryByText(/connection lost/)).toBeNull();
    vi.useRealTimers();
  });

  it("shows a backend error in place of the answer", async () => {
    api.streamKnowledgeChat.mockReturnValue(events([{ type: "error", message: "model unavailable" }]));
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    ask("q");
    expect(await screen.findByText("model unavailable")).toBeInTheDocument();
  });

  it("forks a strand after an answer and opens it", async () => {
    const parent = { id: "c1", title: "Parent", created_at: "1", updated_at: "1", compacted: false, message_count: 2 };
    const fork = { ...parent, id: "c2", parent_id: "c1", fork_at: 1, fork_kind: "strand" };
    api.listConversations.mockResolvedValue([parent, fork]);
    api.getConversationMessages.mockResolvedValue([msg("u1", "user", "First question"), msg("a1", "assistant", "First answer")]);
    api.forkConversation.mockResolvedValue(fork);
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    fireEvent.click(await screen.findByText("Parent"));
    fireEvent.click(await screen.findByTitle(/Spin a new strand off/));
    await waitFor(() => expect(api.forkConversation).toHaveBeenCalledWith("c1", 1, "strand"));
    expect(await screen.findByText("↑ Parent")).toBeInTheDocument();
  });
});

describe("KnowledgeChat trace, sources, stop and retry", () => {
  const ID = "c7d9ec3d-0df1-4c18-970f-7f6dc34e5e3e";

  it("moves interim prose into the trace, shows tool calls and links the sources to /paper/<id>", async () => {
    api.streamKnowledgeChat.mockReturnValue(events([
      { type: "conversation", conversation_id: "c1", user_message_id: "u1" },
      { type: "step", description: "Sending to Claude…" },
      { type: "token", text: "I will search the library." },
      { type: "interim" },
      { type: "step", kind: "search", tool: "semantic_search", description: "Find", input: { query: "alphafold" }, count: 1,
        papers: [{ id: ID, title: "AlphaFold 3", year: 2024 }], result: "[{\"id\": 1}]" },
      { type: "token", text: `The answer cites [AlphaFold 3](/paper/${ID}).` },
      { type: "done", conversation_id: "c1", message_id: "a1" },
    ] as never));
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    ask("q");
    expect(await screen.findByText("✦ Visualise")).toBeInTheDocument();
    expect(screen.getByText("I will search the library.").closest(".kc-trace-text")).not.toBeNull();
    expect(document.querySelectorAll(".kc-tool")).toHaveLength(1);
    expect(screen.getByText("“alphafold”")).toBeInTheDocument();
    const chip = document.querySelector(`.kc-turn-sources a[href="/paper/${ID}"]`)!;
    expect(chip).toHaveAttribute("title", "cited, found");
    fireEvent.click(chip);
    expect(await screen.findByLabelText("Preview")).toBeInTheDocument();
  });

  it("stop tells the server through the question's id, keeps the partial answer and offers retry", async () => {
    let finish!: () => void;
    api.streamKnowledgeChat.mockImplementation(async function* () {
      yield { type: "conversation", conversation_id: "c1", user_message_id: "u1" };
      yield { type: "token", text: "Partial thought" };
      await new Promise<void>((r) => { finish = r; });
      yield { type: "done", conversation_id: "c1", message_id: "a1", stopped: true };
    });
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    ask("long question");
    expect(await screen.findByText("Partial thought")).toBeInTheDocument();
    fireEvent.click(screen.getByText("■ Stop"));
    expect(api.stopKnowledgeChat).toHaveBeenCalledWith("u1");
    await act(async () => { finish(); });
    expect(await screen.findByText("stopped")).toBeInTheDocument();
    expect(screen.getByText("Partial thought")).toBeInTheDocument();
    expect(screen.getByText("retry")).toBeInTheDocument();
  });

  it("stop without a known question id just aborts the request", async () => {
    api.streamKnowledgeChat.mockImplementation(async function* (_b: unknown, signal: AbortSignal) {
      await new Promise<void>((_r, rej) => signal.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError"))));
      yield { type: "token", text: "never" };
    });
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    ask("q");
    fireEvent.click(await screen.findByText("■ Stop"));
    expect(api.stopKnowledgeChat).not.toHaveBeenCalled();
    expect(await screen.findByText("stopped")).toBeInTheDocument();
  });

  it("retry resends the last question with retry_of and replaces the failed answer", async () => {
    api.listConversations.mockResolvedValue([{ id: "c1", title: "Chat", created_at: "1", updated_at: "1", compacted: false, message_count: 2 }]);
    api.getConversationMessages.mockResolvedValue([
      msg("u1", "user", "first", {}), msg("a1", "assistant", "first answer"),
      msg("u2", "user", "second", { answer_error: "model unavailable" }),
    ]);
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    fireEvent.click(await screen.findByText("Chat"));
    expect(await screen.findByText("model unavailable")).toBeInTheDocument();
    api.streamKnowledgeChat.mockReturnValue(events([
      { type: "token", text: "Now it works." }, { type: "done", conversation_id: "c1", message_id: "a2" },
    ]));
    fireEvent.click(screen.getByText("retry"));
    expect(await screen.findByText("Now it works.")).toBeInTheDocument();
    const body = api.streamKnowledgeChat.mock.calls[0][0];
    expect(body).toMatchObject({ question: "second", conversation_id: "c1", retry_of: "u2" });
    expect(body.history).toEqual([{ role: "user", content: "first" }, { role: "assistant", content: "first answer" }]);
    expect(screen.queryByText("model unavailable")).toBeNull();
    expect(screen.getAllByText("second")).toHaveLength(1);
    expect(screen.queryByText("retry")).toBeNull();
  });

  it("retry without a server id resends without retry_of", async () => {
    api.streamKnowledgeChat.mockReturnValueOnce(events([{ type: "error", message: "boom" }]));
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    ask("q");
    expect(await screen.findByText("boom")).toBeInTheDocument();
    api.streamKnowledgeChat.mockReturnValueOnce(events([{ type: "token", text: "ok" }, { type: "done", conversation_id: "c1", message_id: "a1" }]));
    fireEvent.click(screen.getByText("retry"));
    expect(await screen.findByText("ok")).toBeInTheDocument();
    expect(api.streamKnowledgeChat.mock.calls[1][0]).not.toHaveProperty("retry_of");
  });

  it("offers no retry on a complete answer", async () => {
    api.streamKnowledgeChat.mockReturnValue(events([{ type: "token", text: "fine" }, { type: "done", conversation_id: "c1", message_id: "a1" }]));
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    ask("q");
    await screen.findByText("fine");
    expect(screen.queryByText("retry")).toBeNull();
  });

  it("a saved conversation shows its tool calls, sources and stopped note from the stored steps", async () => {
    api.listConversations.mockResolvedValue([{ id: "c1", title: "Saved", created_at: "1", updated_at: "1", compacted: false, message_count: 2 }]);
    api.getConversationMessages.mockResolvedValue([
      msg("u1", "user", "q"),
      msg("a1", "assistant", "Partial", {
        stopped: true,
        steps: [{ kind: "text", description: "", text: "Checking first." }, { tool: "load_full_text", description: "Reading", papers: [{ id: ID, title: "AF3" }] }],
      } as never),
    ]);
    render(<MemoryRouter><KnowledgeChat /></MemoryRouter>);
    fireEvent.click(await screen.findByText("Saved"));
    expect(await screen.findByText("Checking first.")).toBeInTheDocument();
    expect(screen.getByText("Read")).toBeInTheDocument();
    expect(document.querySelector(`.kc-turn-sources a[href="/paper/${ID}"]`)).toHaveAttribute("title", "read");
    expect(screen.getByText("stopped")).toBeInTheDocument();
  });
});

describe("toItems / awaitSavedAnswer", () => {
  it("turns stored messages into items, with a failed question's error in place of its answer", () => {
    const items = toItems([
      msg("s", "system", "summary"),
      msg("u1", "user", "q1"), msg("a1", "assistant", "a1", { concepts: [], concepts_status: "done" }),
      msg("u2", "user", "q2", { answer_error: "boom" }),
    ]);
    expect(items.map((i) => i.kind)).toEqual(["system", "user", "assistant", "user", "assistant"]);
    expect(items[4]).toMatchObject({ error: "boom", id: undefined });
    expect(items[2]).toMatchObject({ id: "a1", conceptsStatus: "done" });
  });

  it("keeps the saved steps and the stopped flag of an answer", () => {
    const steps = [{ kind: "text", description: "", text: "hm" }, { tool: "run_cypher", description: "Count" }];
    const items = toItems([msg("u1", "user", "q"), msg("a1", "assistant", "partial", { steps, stopped: true } as never), msg("u2", "user", "q2"), msg("a2", "assistant", "old")]);
    expect(items[0]).toMatchObject({ kind: "user", id: "u1" });
    expect(items[1]).toMatchObject({ id: "a1", steps, stopped: true });
    expect(items[3]).toMatchObject({ id: "a2", steps: [], stopped: false });
  });

  it("returns the answer once saved, or the saved error", async () => {
    api.getConversationMessages
      .mockResolvedValueOnce([msg("u1", "user", "q")])
      .mockResolvedValueOnce([msg("u1", "user", "q"), msg("a1", "assistant", "done")]);
    const got = await awaitSavedAnswer("c1", "u1", { every: 1 });
    expect(got).toMatchObject({ id: "a1", content: "done" });
    api.getConversationMessages.mockResolvedValueOnce([msg("u1", "user", "q", { answer_error: "boom" })]);
    expect(await awaitSavedAnswer("c1", "u1", { every: 1 })).toEqual({ error: "boom" });
  });

  it("gives up after its timeout", async () => {
    api.getConversationMessages.mockResolvedValue([msg("u1", "user", "q")]);
    const got = await awaitSavedAnswer("c1", "u1", { every: 1, timeout: 20 });
    expect(got).toHaveProperty("error");
  });
});
