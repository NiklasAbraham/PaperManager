import { useState, useRef, useEffect } from "react";
import { useUser } from "../contexts/UserContext";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export default function UserPicker() {
  const { currentUser, setCurrentUser } = useUser();
  const [open, setOpen] = useState(false);
  const [users, setUsers] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  // Show picker immediately if no user is set
  useEffect(() => {
    if (!currentUser) setOpen(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    fetch(`${BASE}/users`)
      .then((r) => r.json())
      .then((data: { name: string }[]) => setUsers(data.map((u) => u.name)))
      .catch(() => {});
  }, [open]);

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        if (currentUser) setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [currentUser]);

  function select(name: string) {
    setCurrentUser(name);
    setOpen(false);
    setInput("");
  }

  function submit() {
    const name = input.trim();
    if (name) select(name);
  }

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex max-w-56 items-center gap-2 px-3 py-1.5 rounded border text-sm font-medium transition-colors border-violet-300 bg-violet-50 text-violet-700 hover:bg-violet-100"
      >
        <span className="w-5 h-5 rounded-full bg-violet-200 text-violet-800 flex items-center justify-center text-xs font-bold select-none">
          {currentUser ? currentUser[0].toUpperCase() : "?"}
        </span>
        <span className="truncate">{currentUser ?? "Set name"}</span>
        <svg className="w-3 h-3 opacity-50" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-64 max-w-[calc(100vw-1rem)] box-border bg-white border border-gray-200 rounded-lg shadow-lg z-50 p-3 flex flex-col gap-2">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Who are you?</p>
          {users.length > 0 && (
            <div className="flex max-h-56 flex-col gap-1 overflow-auto">
              {users.map((u) => (
                <button
                  key={u}
                  onClick={() => select(u)}
                  className={`text-left px-3 py-1.5 rounded text-sm transition-colors truncate ${
                    u === currentUser
                      ? "bg-violet-100 text-violet-700 font-semibold"
                      : "hover:bg-gray-100 text-gray-700"
                  }`}
                >
                  {u}
                </button>
              ))}
            </div>
          )}
          <div className="mt-1 flex items-stretch gap-1 min-w-0">
            <input
              autoFocus
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="New name…"
              className="flex-1 min-w-0 border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-violet-400"
            />
            <button
              onClick={submit}
              disabled={!input.trim()}
              className="shrink-0 px-2 py-1 rounded bg-violet-600 text-white text-sm disabled:opacity-40 hover:bg-violet-700"
            >
              Go
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
