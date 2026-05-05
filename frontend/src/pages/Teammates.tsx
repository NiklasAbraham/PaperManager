import { useState, useEffect } from "react";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

interface UserInfo {
  name: string;
  paper_count: number;
  conversation_count: number;
}

export default function Teammates() {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [selectedUser, setSelectedUser] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [messageCount, setMessageCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${BASE}/users`)
      .then((r) => r.json())
      .then(setUsers)
      .catch(() => {});
  }, []);

  async function ask() {
    if (!selectedUser || !question.trim()) return;
    setLoading(true);
    setAnswer(null);
    setError(null);
    try {
      const res = await fetch(`${BASE}/users/${encodeURIComponent(selectedUser)}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim() }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setAnswer(data.answer);
      setMessageCount(data.message_count);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Ask a Teammate</h1>
        <p className="text-sm text-gray-500 mt-1">
          Ask Claude what a teammate has been thinking about, based on their conversation history.
        </p>
      </div>

      {/* User selector */}
      <div className="flex flex-wrap gap-2">
        {users.map((u) => (
          <button
            key={u.name}
            onClick={() => { setSelectedUser(u.name); setAnswer(null); }}
            className={`px-4 py-2 rounded-full border text-sm font-medium transition-colors ${
              selectedUser === u.name
                ? "bg-violet-600 border-violet-600 text-white"
                : "bg-white border-gray-200 text-gray-700 hover:border-violet-300 hover:text-violet-700"
            }`}
          >
            <span className="mr-1.5 opacity-70">{u.name[0].toUpperCase()}</span>
            {u.name}
            <span className="ml-2 text-[11px] opacity-60">
              {u.conversation_count} conv · {u.paper_count} papers
            </span>
          </button>
        ))}
        {users.length === 0 && (
          <p className="text-sm text-gray-400">No teammates yet — set a name in the top-right corner to get started.</p>
        )}
      </div>

      {/* Question input */}
      {selectedUser && (
        <div className="flex flex-col gap-3">
          <label className="text-sm font-medium text-gray-700">
            What do you want to know about{" "}
            <span className="text-violet-700">{selectedUser}</span>'s thinking?
          </label>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask(); }}
            placeholder={`Has ${selectedUser} thought about reinforcement learning? What approach is ${selectedUser} planning?`}
            rows={3}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none"
          />
          <button
            onClick={ask}
            disabled={loading || !question.trim()}
            className="self-start px-5 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-40 transition-colors"
          >
            {loading ? "Searching conversations…" : "Ask"}
          </button>
          <p className="text-[11px] text-gray-400">Tip: ⌘/Ctrl+Enter to submit</p>
        </div>
      )}

      {/* Answer */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>
      )}
      {answer && (
        <div className="bg-white border border-gray-200 rounded-lg p-5 flex flex-col gap-3">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span className="w-5 h-5 rounded-full bg-violet-100 text-violet-700 flex items-center justify-center font-bold text-[10px]">
              {selectedUser![0].toUpperCase()}
            </span>
            Based on {messageCount} messages from {selectedUser}'s conversations
          </div>
          <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">{answer}</p>
        </div>
      )}
    </div>
  );
}
