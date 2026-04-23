import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { listChapters, detectChapters, regenerateChapterSummary, chatWithChapter } from "../api/client";
import type { Chapter } from "../types";

interface Props {
  paperId: string;
}

export default function BookChapters({ paperId }: Props) {
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [loading, setLoading] = useState(true);
  const [detecting, setDetecting] = useState(false);
  const [useAi, setUseAi] = useState(false);
  const [detectError, setDetectError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState<string | null>(null);

  // Per-chapter chat
  const [chatChapterId, setChatChapterId] = useState<string | null>(null);
  const [chatQuestion, setChatQuestion] = useState("");
  const [chatHistory, setChatHistory] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [chatAnswering, setChatAnswering] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    listChapters(paperId)
      .then(setChapters)
      .catch(() => setChapters([]))
      .finally(() => setLoading(false));
  }, [paperId]);

  const handleDetect = async () => {
    setDetecting(true);
    setDetectError(null);
    try {
      const result = await detectChapters(paperId, useAi);
      setChapters(result);
    } catch (e) {
      setDetectError(e instanceof Error ? e.message : "Chapter detection failed");
    } finally {
      setDetecting(false);
    }
  };

  const handleRegenerateSummary = async (chapterId: string) => {
    setRegenerating(chapterId);
    try {
      const updated = await regenerateChapterSummary(paperId, chapterId);
      setChapters((prev) => prev.map((c) => (c.id === chapterId ? updated : c)));
    } catch { /* best-effort */ }
    setRegenerating(null);
  };

  const openChat = (chapterId: string) => {
    if (chatChapterId === chapterId) {
      setChatChapterId(null);
    } else {
      setChatChapterId(chapterId);
      setChatHistory([]);
      setChatQuestion("");
      setChatError(null);
    }
  };

  const sendChatMessage = async () => {
    if (!chatChapterId || !chatQuestion.trim()) return;
    const q = chatQuestion.trim();
    setChatQuestion("");
    setChatHistory((prev) => [...prev, { role: "user", content: q }]);
    setChatAnswering(true);
    setChatError(null);
    try {
      const history = chatHistory.map((m) => ({ role: m.role, content: m.content }));
      const res = await chatWithChapter(paperId, chatChapterId, q, history);
      setChatHistory((prev) => [...prev, { role: "assistant", content: res.answer }]);
    } catch (e) {
      setChatError(e instanceof Error ? e.message : "Chat failed");
    } finally {
      setChatAnswering(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-gray-400">
        Loading chapters…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={handleDetect}
          disabled={detecting}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors"
        >
          {detecting && (
            <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
            </svg>
          )}
          {detecting ? "Detecting chapters…" : chapters.length > 0 ? "🔄 Re-detect chapters" : "🔍 Detect chapters"}
        </button>
        <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={useAi}
            onChange={(e) => setUseAi(e.target.checked)}
            className="rounded"
          />
          Use AI for detection
        </label>
        {chapters.length > 0 && (
          <span className="ml-auto text-xs text-gray-400">{chapters.length} chapter{chapters.length !== 1 ? "s" : ""}</span>
        )}
      </div>

      {detectError && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700">
          {detectError}
        </div>
      )}

      {chapters.length === 0 && !detecting && (
        <div className="rounded-lg bg-gray-50 border border-gray-200 px-4 py-6 text-center text-sm text-gray-400">
          <p className="font-medium mb-1">No chapters detected yet.</p>
          <p>Click <strong>Detect chapters</strong> to automatically analyze this document's structure and generate per-chapter summaries.</p>
        </div>
      )}

      {/* Chapter list */}
      <div className="space-y-2">
        {chapters.map((ch) => {
          const isExpanded = expandedId === ch.id;
          const isChatOpen = chatChapterId === ch.id;
          return (
            <div key={ch.id} className={`rounded-lg border transition-colors ${ch.level === 2 ? "ml-4 border-gray-100 bg-gray-50" : "border-gray-200 bg-white"}`}>
              {/* Chapter header */}
              <button
                className="w-full text-left px-4 py-3 flex items-center gap-2 hover:bg-gray-50 rounded-lg"
                onClick={() => setExpandedId(isExpanded ? null : ch.id)}
              >
                <span className={`text-xs font-mono shrink-0 ${ch.level === 2 ? "text-gray-400" : "text-violet-500"}`}>
                  {ch.level === 2 ? "§" : "Ch."} {ch.number}
                </span>
                <span className={`flex-1 font-medium text-sm text-gray-800 text-left ${ch.level === 2 ? "text-xs" : ""}`}>
                  {ch.title}
                </span>
                <span className="shrink-0 text-gray-400 text-xs">{isExpanded ? "▲" : "▼"}</span>
              </button>

              {/* Expanded content */}
              {isExpanded && (
                <div className="px-4 pb-4 space-y-3 border-t border-gray-100 pt-3">
                  {/* Summary */}
                  {ch.summary ? (
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Summary</p>
                        <button
                          onClick={() => handleRegenerateSummary(ch.id)}
                          disabled={regenerating === ch.id}
                          className="text-xs text-gray-400 hover:text-violet-600 transition-colors flex items-center gap-1"
                        >
                          {regenerating === ch.id ? (
                            <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                            </svg>
                          ) : "↺"} Regenerate
                        </button>
                      </div>
                      <div className="text-sm text-gray-700 prose prose-sm max-w-none">
                        <ReactMarkdown>{ch.summary}</ReactMarkdown>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <p className="text-xs text-gray-400 italic">No summary yet.</p>
                      <button
                        onClick={() => handleRegenerateSummary(ch.id)}
                        disabled={regenerating === ch.id}
                        className="text-xs text-violet-600 hover:text-violet-800 transition-colors flex items-center gap-1"
                      >
                        {regenerating === ch.id ? "Generating…" : "✦ Generate summary"}
                      </button>
                    </div>
                  )}

                  {/* Chat button */}
                  <div>
                    <button
                      onClick={() => openChat(ch.id)}
                      className="text-xs px-2.5 py-1 rounded-lg border border-violet-300 text-violet-600 hover:bg-violet-50 transition-colors font-medium"
                    >
                      {isChatOpen ? "✕ Close chat" : "💬 Ask about this chapter"}
                    </button>
                  </div>

                  {/* Chat panel */}
                  {isChatOpen && (
                    <div className="rounded-lg border border-violet-100 bg-violet-50 p-3 space-y-2">
                      <div className="max-h-48 overflow-y-auto space-y-2 text-sm">
                        {chatHistory.map((msg, i) => (
                          <div key={i} className={`${msg.role === "user" ? "text-right" : "text-left"}`}>
                            <span className={`inline-block rounded-lg px-2.5 py-1.5 text-xs max-w-[90%] ${msg.role === "user" ? "bg-violet-600 text-white" : "bg-white text-gray-800 border border-gray-200"}`}>
                              {msg.role === "assistant" ? (
                                <ReactMarkdown>{msg.content}</ReactMarkdown>
                              ) : msg.content}
                            </span>
                          </div>
                        ))}
                        {chatAnswering && (
                          <div className="text-left">
                            <span className="inline-block rounded-lg px-2.5 py-1.5 text-xs bg-white text-gray-400 border border-gray-200 animate-pulse">
                              Thinking…
                            </span>
                          </div>
                        )}
                      </div>
                      {chatError && <p className="text-xs text-red-600">{chatError}</p>}
                      <div className="flex gap-2">
                        <input
                          value={chatQuestion}
                          onChange={(e) => setChatQuestion(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChatMessage(); } }}
                          placeholder="Ask a question about this chapter…"
                          className="flex-1 border border-gray-200 rounded px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white"
                          disabled={chatAnswering}
                        />
                        <button
                          onClick={sendChatMessage}
                          disabled={chatAnswering || !chatQuestion.trim()}
                          className="px-2.5 py-1.5 text-xs bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
                        >
                          Send
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
