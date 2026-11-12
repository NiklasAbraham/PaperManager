import { useEffect, useState } from "react";
import type { EntityType } from "../EntityPanel";

interface Props {
  surprising: boolean;
  onSurprise: () => void;
  onGaps: () => void;
  onManage: (type: EntityType) => void;
}

const MANAGE: { type: EntityType; label: string }[] = [
  { type: "tags", label: "Manage tags" },
  { type: "topics", label: "Manage topics" },
  { type: "authors", label: "Manage authors" },
  { type: "projects", label: "Manage projects" },
];

/** The overflow (three dots) menu of the Library bar: the occasional actions. */
export default function LibraryMenu({ surprising, onSurprise, onGaps, onManage }: Props) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const run = (fn: () => void) => () => { setOpen(false); fn(); };
  const item = "w-full text-left px-3 py-1.5 text-sm text-ink-2 hover:bg-accent-lo hover:text-accent disabled:opacity-50";

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="More actions"
        aria-expanded={open}
        aria-haspopup="menu"
        className="h-9 w-9 inline-flex items-center justify-center rounded-lg border border-line text-ink-3 hover:text-accent hover:border-accent-border transition-colors"
      >
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
        </svg>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden="true" />
          <div role="menu" className="absolute right-0 top-full mt-2 z-40 w-52 bg-raised border border-line rounded-xl shadow-xl py-1">
            <button role="menuitem" className={item} disabled={surprising} onClick={run(onSurprise)}>Surprise me</button>
            <button role="menuitem" className={item} onClick={run(onGaps)}>Find research gaps</button>
            <div className="my-1 border-t border-line-s" />
            {MANAGE.map((m) => (
              <button key={m.type} role="menuitem" className={item} onClick={run(() => onManage(m.type))}>{m.label}</button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
