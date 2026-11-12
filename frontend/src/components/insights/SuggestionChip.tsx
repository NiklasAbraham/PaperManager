import { useState } from "react";
import { Link } from "react-router-dom";
import { voteSuggestion } from "../../api/insights";
import type { SuggestionOut } from "../../api/insights";

const KEY = "pm_dismissed_suggestion_chips";
const CAP = 200;

function readDismissed(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** True when the user has closed the chip for this suggestion before. */
export function isSuggestionChipDismissed(id: string): boolean {
  return readDismissed().includes(id);
}

function rememberDismissed(id: string) {
  try {
    const next = [...readDismissed().filter((x) => x !== id), id].slice(-CAP);
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage full or blocked: the chip is hidden for this session only */
  }
}

function BulbIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-accent">
      <path d="M9 18h6" />
      <path d="M10 21h4" />
      <path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3Z" />
    </svg>
  );
}

/** A quiet chip under a chat answer: the suggestion the assistant noted, a vote, a link to the list, and a close button. */
export default function SuggestionChip({
  suggestion,
  onDismiss,
}: {
  suggestion: SuggestionOut;
  onDismiss?: (id: string) => void;
}) {
  const [hidden, setHidden] = useState(() => isSuggestionChipDismissed(suggestion.id));
  const [voted, setVoted] = useState(suggestion.voted);
  const [votes, setVotes] = useState(suggestion.votes);
  const [busy, setBusy] = useState(false);

  if (hidden) return null;

  const vote = async () => {
    if (busy) return;
    const prev = { voted, votes };
    setBusy(true);
    setVoted(!voted);
    setVotes(Math.max(0, votes + (voted ? -1 : 1)));
    try {
      const next = await voteSuggestion(suggestion.id);
      setVoted(next.voted);
      setVotes(next.votes);
    } catch {
      setVoted(prev.voted);
      setVotes(prev.votes);
    } finally {
      setBusy(false);
    }
  };

  const dismiss = () => {
    rememberDismissed(suggestion.id);
    setHidden(true);
    onDismiss?.(suggestion.id);
  };

  return (
    <div
      role="note"
      aria-label="Suggestion from the assistant"
      className="mt-2 flex max-w-full items-center gap-2 rounded-full border border-line bg-line-s py-1 pl-3 pr-1.5 text-xs text-ink-2"
    >
      <BulbIcon />
      <span className="min-w-0 truncate" title={suggestion.text}>
        <span className="font-medium text-ink">Suggestion:</span> {suggestion.text}
      </span>
      <button
        type="button"
        onClick={vote}
        disabled={busy}
        aria-pressed={voted}
        aria-label={voted ? `Remove your vote, ${votes} votes` : `Vote for this suggestion, ${votes} votes`}
        className={`shrink-0 rounded-full border px-2 py-0.5 tabular-nums focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border ${
          voted ? "border-accent bg-accent text-white" : "border-line bg-raised text-ink-2 hover:border-accent-border hover:text-accent"
        }`}
      >
        {voted ? "Voted" : "+1"} {votes > 0 ? votes : ""}
      </button>
      <Link
        to="/suggestions"
        className="shrink-0 whitespace-nowrap text-accent hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border"
      >
        All suggestions
      </Link>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss suggestion"
        className="shrink-0 rounded-full px-1.5 text-base leading-none text-ink-3 hover:text-ink-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border"
      >
        <span aria-hidden="true">&times;</span>
      </button>
    </div>
  );
}
