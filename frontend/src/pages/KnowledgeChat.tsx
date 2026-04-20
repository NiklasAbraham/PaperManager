import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  listConversations, getConversationMessages,
  compactConversation, deleteConversation, streamKnowledgeChat,
  apiFetch,
} from "../api/client";
import type {
  Conversation, KnowledgeMessage, ContextPaper, TokenTotals, SseEvent,
  Tag, Topic, Project, Paper,
} from "../types";

const CONTEXT_LIMIT = 200_000;
type Model = "claude" | "claude-work" | "ollama";
const MODEL_LABELS: Record<Model, string> = { claude: "Claude", "claude-work": "Claude (Work)", ollama: "Ollama" };

// ── Context Bar ───────────────────────────────────────────────────────────────

function ContextBar({ totals, papers, answerTokens }: { totals: TokenTotals | null; papers: ContextPaper[]; answerTokens: number }) {
  const limit = totals?.limit ?? CONTEXT_LIMIT;
  const total = (totals?.total ?? 0) + answerTokens;
  const pct = Math.min(100, (total / limit) * 100);
  const isWarning = pct > 80;

  const segments: { label: string; tokens: number; color: string }[] = [];
  if (totals) {
    segments.push({ label: "System prompt", tokens: totals.system, color: "#374151" });
    papers.forEach((p) => segments.push({ label: p.title, tokens: p.tokens, color: p.color }));
    if (totals.history > 0) segments.push({ label: "Conversation history", tokens: totals.history, color: "#f97316" });
    if (totals.question > 0) segments.push({ label: "Current question", tokens: totals.question, color: "#22c55e" });
    if (answerTokens > 0) segments.push({ label: "Answer (streaming)", tokens: answerTokens, color: "#06b6d4" });
  }

  return (
    <div className="px-4 py-3 bg-gray-950 border-b border-gray-800">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Context window</span>
        <span className={`text-xs font-mono ml-auto ${isWarning ? "text-red-400" : "text-gray-400"}`}>
          {total.toLocaleString()} / {limit.toLocaleString()} tokens · {pct.toFixed(1)}%
        </span>
      </div>

      {/* Bar */}
      <div className="w-full h-5 bg-gray-800 rounded overflow-hidden flex relative group">
        {totals ? (
          segments.map((seg, i) => {
            const segPct = (seg.tokens / limit) * 100;
            return (
              <div
                key={i}
                style={{ width: `${Math.max(segPct, 0.15)}%`, backgroundColor: seg.color }}
                className="h-full transition-all duration-150"
                title={`${seg.label}: ${seg.tokens.toLocaleString()} tokens`}
              />
            );
          })
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[10px] text-gray-600">
            Send a message to see context usage
          </div>
        )}
        {/* Empty remainder */}
        {totals && (
          <div className="flex-1 h-full bg-transparent" />
        )}
      </div>

      {/* Legend */}
      {totals && segments.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5">
          {segments.map((seg, i) => (
            <span key={i} className="flex items-center gap-1 text-[10px] text-gray-500">
              <span className="inline-block w-2 h-2 rounded-sm flex-shrink-0" style={{ backgroundColor: seg.color }} />
              {seg.label.length > 30 ? seg.label.slice(0, 28) + "…" : seg.label}
              <span className="text-gray-600">({seg.tokens.toLocaleString()})</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Reasoning Step Card ───────────────────────────────────────────────────────

function StepCard({ description, cypher, count }: { description: string; cypher?: string; count?: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="my-1 rounded border border-gray-700 bg-gray-900 text-xs overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left text-gray-400 hover:text-gray-200 transition-colors"
      >
        <span className="text-gray-600">{open ? "▼" : "▶"}</span>
        <span className="flex-1 font-mono text-green-400">{description}</span>
        {count != null && (
          <span className="ml-auto px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 text-[10px]">
            {count} result{count !== 1 ? "s" : ""}
          </span>
        )}
      </button>
      {open && cypher && (
        <pre className="px-4 py-2 bg-gray-950 text-green-300 font-mono text-[11px] overflow-x-auto whitespace-pre-wrap border-t border-gray-700">
          {cypher}
        </pre>
      )}
    </div>
  );
}

// ── @mention autocomplete ────────────────────────────────────────────────────

type MentionOption = { type: string; value: string; label: string };

function MentionDropdown({
  options, onSelect,
}: { options: MentionOption[]; onSelect: (o: MentionOption) => void }) {
  if (!options.length) return null;
  return (
    <div className="absolute bottom-full mb-1 left-0 right-0 bg-gray-900 border border-gray-700 rounded-lg shadow-xl max-h-48 overflow-y-auto z-50">
      {options.map((o, i) => (
        <button
          key={i}
          onMouseDown={(e) => { e.preventDefault(); onSelect(o); }}
          className="w-full text-left px-3 py-2 text-xs hover:bg-gray-800 flex items-center gap-2"
        >
          <span className="text-gray-500 font-mono text-[10px] bg-gray-800 px-1 rounded">{o.type}</span>
          <span className="text-gray-200">{o.label}</span>
        </button>
      ))}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type DisplayMessage =
  | { kind: "step"; description: string; cypher?: string; count?: number }
  | { kind: "chat"; role: "user" | "assistant" | "system"; content: string; streaming?: boolean };

export default function KnowledgeChat() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState<Model>("claude");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contextPapers, setContextPapers] = useState<ContextPaper[]>([]);
  const [tokenTotals, setTokenTotals] = useState<TokenTotals | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [compacting, setCompacting] = useState(false);
  const [answerTokens, setAnswerTokens] = useState(0);

  // Autocomplete
  const [allTags, setAllTags] = useState<string[]>([]);
  const [allTopics, setAllTopics] = useState<string[]>([]);
  const [allProjects, setAllProjects] = useState<string[]>([]);
  const [allPapers, setAllPapers] = useState<string[]>([]);
  const [mentionDropdown, setMentionDropdown] = useState<MentionOption[]>([]);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load entity lists for autocomplete
  useEffect(() => {
    apiFetch<Tag[]>("/tags").then((t) => setAllTags(t.map((x) => x.name))).catch(() => {});
    apiFetch<Topic[]>("/topics").then((t) => setAllTopics(t.map((x) => x.name))).catch(() => {});
    apiFetch<{ id: string; name: string }[]>("/projects").then((p) => setAllProjects(p.map((x) => x.name))).catch(() => {});
    apiFetch<Paper[]>("/papers").then((p) => setAllPapers(p.map((x) => x.title))).catch(() => {});
    listConversations().then(setConversations).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Handle @mention autocomplete
  const handleInputChange = (val: string) => {
    setInput(val);
    const cursor = textareaRef.current?.selectionStart ?? val.length;
    const before = val.slice(0, cursor);
    const match = before.match(/@(project|tag|topic|paper)?:?(\w*)$/i);
    if (!match) { setMentionDropdown([]); return; }

    const [, type, partial] = match;
    const p = partial.toLowerCase();

    const opts: MentionOption[] = [];
    if (!type || type === "tag") {
      allTags.filter((n) => n.includes(p)).slice(0, 5).forEach((n) =>
        opts.push({ type: "tag", value: n, label: n }));
    }
    if (!type || type === "topic") {
      allTopics.filter((n) => n.toLowerCase().includes(p)).slice(0, 5).forEach((n) =>
        opts.push({ type: "topic", value: n, label: n }));
    }
    if (!type || type === "project") {
      allProjects.filter((n) => n.toLowerCase().includes(p)).slice(0, 5).forEach((n) =>
        opts.push({ type: "project", value: n, label: n }));
    }
    if (!type || type === "paper") {
      allPapers.filter((n) => n.toLowerCase().includes(p)).slice(0, 3).forEach((n) =>
        opts.push({ type: "paper", value: n, label: n }));
    }
    setMentionDropdown(opts.slice(0, 8));
  };

  const insertMention = (opt: MentionOption) => {
    const cursor = textareaRef.current?.selectionStart ?? input.length;
    const before = input.slice(0, cursor);
    const after = input.slice(cursor);
    const replaced = before.replace(/@[\w:]*$/, `@${opt.type}:${opt.value} `);
    setInput(replaced + after);
    setMentionDropdown([]);
    setTimeout(() => textareaRef.current?.focus(), 0);
  };

  // Load conversation
  const loadConversation = async (conv: Conversation) => {
    setActiveConvId(conv.id);
    setMessages([]);
    setTokenTotals(null);
    setContextPapers([]);
    setAnswerTokens(0);
    const msgs = await getConversationMessages(conv.id);
    const display: DisplayMessage[] = msgs.map((m) => ({
      kind: "chat" as const,
      role: m.role as "user" | "assistant" | "system",
      content: m.content,
    }));
    setMessages(display);
  };

  const newConversation = () => {
    setActiveConvId(null);
    setMessages([]);
    setTokenTotals(null);
    setContextPapers([]);
    setAnswerTokens(0);
    setInput("");
  };

  // Send message
  const send = async () => {
    const question = input.trim();
    if (!question || loading) return;
    setInput("");
    setMentionDropdown([]);
    setError(null);
    setLoading(true);
    setAnswerTokens(0);

    const history = messages
      .filter((m): m is Extract<DisplayMessage, { kind: "chat" }> => m.kind === "chat")
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, { kind: "chat", role: "user", content: question }]);

    let accAnswer = "";

    try {
      const stream = streamKnowledgeChat({
        question,
        history,
        model,
        conversation_id: activeConvId ?? undefined,
      });

      for await (const event of stream) {
        if (event.type === "step") {
          // Append step — never touch existing messages
          setMessages((prev) => [...prev, {
            kind: "step",
            description: event.description,
            cypher: event.cypher,
            count: event.count,
          }]);

        } else if (event.type === "context") {
          setContextPapers(event.papers);
          setTokenTotals(event.token_totals);

        } else if (event.type === "token") {
          accAnswer += event.text;
          const tok = Math.ceil(accAnswer.length / 4);
          setAnswerTokens(tok);
          // Update or append the single streaming assistant message
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.kind === "chat" && last.role === "assistant" && (last as typeof last & { streaming?: boolean }).streaming) {
              return [...prev.slice(0, -1), { ...last, content: accAnswer }];
            }
            return [...prev, { kind: "chat", role: "assistant", content: accAnswer, streaming: true }];
          });

        } else if (event.type === "done") {
          // Unmark streaming flag on the last assistant message
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.kind === "chat" && last.role === "assistant") {
              return [...prev.slice(0, -1), { ...last, streaming: false }];
            }
            return prev;
          });
          setActiveConvId(event.conversation_id);
          listConversations().then(setConversations).catch(() => {});

        } else if (event.type === "error") {
          setError(event.message);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chat failed");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !mentionDropdown.length) {
      e.preventDefault();
      send();
    }
  };

  const handleCompact = async () => {
    if (!activeConvId) return;
    setCompacting(true);
    try {
      await compactConversation(activeConvId);
      const msgs = await getConversationMessages(activeConvId);
      setMessages(msgs.map((m) => ({ kind: "chat", role: m.role as "user" | "assistant" | "system", content: m.content })));
      const convs = await listConversations();
      setConversations(convs);
    } finally {
      setCompacting(false);
    }
  };

  const handleDelete = async (id: string) => {
    await deleteConversation(id);
    setConversations((c) => c.filter((x) => x.id !== id));
    if (activeConvId === id) newConversation();
    setConfirmDelete(null);
  };

  const activeConv = conversations.find((c) => c.id === activeConvId);

  return (
    <div className="flex flex-col h-full bg-gray-950 text-gray-100">
      {/* Context Bar */}
      <ContextBar totals={tokenTotals} papers={contextPapers} answerTokens={answerTokens} />

      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <aside className="w-56 flex-shrink-0 flex flex-col border-r border-gray-800 bg-gray-900">
          <div className="px-3 py-3 border-b border-gray-800 flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Conversations</span>
            <button
              onClick={newConversation}
              className="text-xs text-violet-400 hover:text-violet-300 font-medium"
            >
              + New
            </button>
          </div>

          <div className="flex-1 overflow-y-auto py-1">
            {conversations.length === 0 && (
              <p className="text-xs text-gray-600 text-center mt-6 px-3">No conversations yet</p>
            )}
            {conversations.map((conv) => (
              <div
                key={conv.id}
                className={`group flex items-start gap-1 px-2 py-2 cursor-pointer rounded mx-1 my-0.5 transition-colors ${
                  activeConvId === conv.id ? "bg-gray-700" : "hover:bg-gray-800"
                }`}
                onClick={() => loadConversation(conv)}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-200 truncate">{conv.title}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">
                    {conv.message_count} msg{conv.message_count !== 1 ? "s" : ""}
                    {conv.compacted && " · compacted"}
                  </p>
                </div>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 flex-shrink-0 mt-0.5">
                  {confirmDelete === conv.id ? (
                    <>
                      <button onClick={(e) => { e.stopPropagation(); handleDelete(conv.id); }} className="text-[10px] text-red-400 hover:text-red-300">del</button>
                      <button onClick={(e) => { e.stopPropagation(); setConfirmDelete(null); }} className="text-[10px] text-gray-500">cancel</button>
                    </>
                  ) : (
                    <button onClick={(e) => { e.stopPropagation(); setConfirmDelete(conv.id); }} className="text-[10px] text-gray-600 hover:text-red-400">×</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </aside>

        {/* Main chat area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="px-4 py-2.5 border-b border-gray-800 flex items-center gap-3 bg-gray-900">
            <div className="flex-1">
              <h1 className="text-sm font-semibold text-gray-200">
                {activeConv ? activeConv.title : "New conversation"}
              </h1>
              {!activeConvId && (
                <p className="text-xs text-gray-500 mt-0.5">
                  Use <span className="font-mono text-violet-400">@tag:name</span>, <span className="font-mono text-blue-400">@topic:name</span>, <span className="font-mono text-green-400">@project:name</span>, or <span className="font-mono text-orange-400">@paper:title</span> to scope context
                </p>
              )}
            </div>

            {/* Model selector */}
            <div className="flex rounded-md border border-gray-700 overflow-hidden text-xs">
              {(["claude", "claude-work", "ollama"] as Model[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setModel(m)}
                  className={`px-2 py-1 transition-colors ${model === m ? "bg-violet-700 text-white" : "text-gray-500 hover:bg-gray-800"}`}
                >
                  {MODEL_LABELS[m]}
                </button>
              ))}
            </div>

            {activeConvId && (
              <button
                onClick={handleCompact}
                disabled={compacting}
                title="Compact conversation (summarise history)"
                className="text-xs px-2 py-1 bg-gray-800 text-gray-400 rounded hover:bg-gray-700 disabled:opacity-50"
              >
                {compacting ? "Compacting…" : "⬡ Compact"}
              </button>
            )}
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-2">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <p className="text-gray-600 text-sm">Ask a question about your library</p>
                <p className="text-gray-700 text-xs mt-2 max-w-sm">
                  Try: <span className="text-violet-400">@tag:drug-discovery what methods are used across these papers?</span>
                </p>
              </div>
            )}

            {messages.map((msg, i) => {
              if (msg.kind === "step") {
                return (
                  <StepCard
                    key={i}
                    description={msg.description}
                    cypher={msg.cypher}
                    count={msg.count}
                  />
                );
              }
              if (msg.role === "system") {
                return (
                  <div key={i} className="text-xs text-gray-600 italic text-center border border-dashed border-gray-800 rounded px-3 py-2">
                    ⬡ Conversation compacted — {msg.content.slice(0, 120)}…
                  </div>
                );
              }
              return (
                <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[80%] rounded-xl px-4 py-2.5 text-sm ${
                      msg.role === "user"
                        ? "bg-violet-700 text-white"
                        : "bg-gray-800 text-gray-100 border border-gray-700"
                    }`}
                  >
                    {msg.role === "assistant" ? (
                      <div className="prose prose-sm prose-invert max-w-none prose-headings:text-gray-100 prose-a:text-violet-400 prose-code:text-green-300">
                        <ReactMarkdown>{msg.content}</ReactMarkdown>
                        {(msg as Extract<DisplayMessage, { kind: "chat" }> & { streaming?: boolean }).streaming && (
                          <span className="inline-block w-1.5 h-4 bg-violet-400 animate-pulse ml-0.5 align-middle" />
                        )}
                      </div>
                    ) : (
                      <span className="whitespace-pre-wrap">{msg.content}</span>
                    )}
                  </div>
                </div>
              );
            })}

            {loading && messages[messages.length - 1]?.kind !== "chat" && (
              <div className="flex justify-start">
                <div className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-gray-500 animate-pulse">
                  {MODEL_LABELS[model]} is thinking…
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {error && (
            <div className="px-4 py-2 text-xs text-red-400 bg-red-950 border-t border-red-900">
              {error}
            </div>
          )}

          {/* Input */}
          <div className="px-4 py-3 border-t border-gray-800 bg-gray-900">
            <div className="relative flex gap-2">
              <div className="relative flex-1">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => handleInputChange(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={loading}
                  rows={2}
                  placeholder="Ask a question… use @tag:name, @topic:name, @project:name, @paper:title to scope context. Enter to send, Shift+Enter for newline."
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none disabled:opacity-50"
                />
                <MentionDropdown options={mentionDropdown} onSelect={insertMention} />
              </div>
              <button
                onClick={send}
                disabled={loading || !input.trim()}
                className="px-4 py-2 bg-violet-700 text-white text-sm rounded-lg hover:bg-violet-600 disabled:opacity-50 transition-colors self-end"
              >
                Ask
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
