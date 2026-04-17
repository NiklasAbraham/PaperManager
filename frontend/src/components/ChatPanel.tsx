import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { apiFetch } from "../api/client";
import type { ChatMessage } from "../types";

type Model = "claude" | "claude-work" | "ollama";

const MODEL_LABELS: Record<Model, string> = {
  claude: "Claude",
  "claude-work": "Claude (Work)",
  ollama: "Ollama",
};

interface Props {
  paperId: string;
}

export default function ChatPanel({ paperId }: Props) {
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState<Model>("claude");

  const send = async () => {
    const question = input.trim();
    if (!question || loading) return;
    setInput("");
    setError(null);

    const newHistory: ChatMessage[] = [...history, { role: "user", content: question }];
    setHistory(newHistory);
    setLoading(true);

    try {
      const res = await apiFetch<{ answer: string }>(`/papers/${paperId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, history, model }),
      });
      setHistory([...newHistory, { role: "assistant", content: res.answer }]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Chat failed");
      setHistory(history); // revert
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = (text: string) => navigator.clipboard.writeText(text);

  return (
    <div className="flex flex-col h-full gap-2">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-gray-700 mr-auto">Chat</h2>
        {/* Model selector */}
        <div className="flex rounded-md border border-gray-200 overflow-hidden text-xs">
          {(["claude", "claude-work", "ollama"] as Model[]).map((m) => (
            <button
              key={m}
              onClick={() => setModel(m)}
              className={`px-2 py-1 transition-colors ${
                model === m
                  ? "bg-violet-600 text-white"
                  : "text-gray-500 hover:bg-gray-50"
              }`}
            >
              {MODEL_LABELS[m]}
            </button>
          ))}
        </div>
        {history.length > 0 && (
          <button
            onClick={() => setHistory([])}
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            Clear
          </button>
        )}
      </div>

      <div className="flex-1 overflow-auto space-y-3 min-h-0">
        {history.length === 0 && (
          <p className="text-xs text-gray-400 text-center mt-4">
            Ask a question about this paper
          </p>
        )}
        {history.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm relative group ${
                msg.role === "user"
                  ? "bg-violet-600 text-white"
                  : "bg-white border border-gray-200 text-gray-800"
              }`}
            >
              {msg.role === "assistant" ? (
                <>
                  <div className="prose prose-sm max-w-none">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                  <button
                    onClick={() => copyToClipboard(msg.content)}
                    className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 text-gray-400 hover:text-gray-600 text-xs"
                    title="Copy"
                  >
                    ⎘
                  </button>
                </>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-400">
              {MODEL_LABELS[model]} is thinking…
            </div>
          </div>
        )}
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          disabled={loading}
          placeholder="Ask a question…"
          className="flex-1 border border-gray-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 disabled:opacity-50"
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          className="px-3 py-1.5 bg-violet-600 text-white text-sm rounded hover:bg-violet-700 disabled:opacity-50"
        >
          Ask
        </button>
      </div>
    </div>
  );
}
