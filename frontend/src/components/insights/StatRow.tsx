import type { ReactNode } from "react";

export interface Stat {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "default" | "error";
}

/** A responsive row of big numbers with a label and an optional muted sub-line. */
export default function StatRow({ stats, label }: { stats: Stat[]; label: string }) {
  return (
    <dl aria-label={label} className="grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-3">
      {stats.map((s) => (
        <div key={s.label} className="rounded-xl border border-line bg-raised px-4 py-3">
          <dt className="text-xs text-ink-3">{s.label}</dt>
          <dd className={`mt-0.5 text-xl font-semibold tabular-nums ${s.tone === "error" ? "text-coral" : "text-ink"}`}>{s.value}</dd>
          {s.sub ? <dd className="mt-0.5 text-xs text-ink-3">{s.sub}</dd> : null}
        </div>
      ))}
    </dl>
  );
}
