import type { ReactNode } from "react";

/** Class strings and small building blocks shared by the insights pages. */

export const inputCls =
  "border border-line rounded-lg bg-raised px-3 py-1.5 text-sm text-ink placeholder:text-ink-3 " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border focus-visible:border-accent";

export const btnPrimary =
  "inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white " +
  "hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border";

export const btnSecondary =
  "inline-flex items-center justify-center gap-1.5 rounded-lg border border-line bg-raised px-3 py-1.5 text-sm text-ink-2 " +
  "hover:border-accent-border hover:text-accent disabled:opacity-40 disabled:cursor-not-allowed " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border";

export const btnDanger =
  "inline-flex items-center justify-center gap-1.5 rounded-lg border border-line bg-raised px-3 py-1.5 text-sm text-coral " +
  "hover:border-coral disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-border";

export function PageHeader({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold text-ink">{title}</h1>
        <p className="mt-1 text-sm text-ink-2">{description}</p>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-8 text-sm text-ink-3">
      <span
        aria-hidden="true"
        className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-line border-t-accent"
      />
      {label}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-coral/30 bg-raised px-4 py-3 text-sm text-coral">
      <span className="min-w-0 break-words">{message}</span>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="rounded border border-line px-2 py-0.5 text-xs text-ink-2 hover:border-accent-border hover:text-accent">
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-raised px-6 py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {children ? <p className="mx-auto mt-1 max-w-md text-sm text-ink-2">{children}</p> : null}
    </div>
  );
}

export function Card({ title, aside, children, className = "" }: { title?: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-line bg-raised p-5 ${className}`}>
      {title ? (
        <div className="mb-3 flex items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          {aside ? <div className="text-xs text-ink-3">{aside}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: "neutral" | "accent" | "ok" | "warn" | "error"; title?: string }) {
  const tones: Record<string, string> = {
    neutral: "bg-line-s text-ink-2 border-line",
    accent: "bg-accent-lo text-accent border-accent-border",
    ok: "bg-emerald-50 text-emerald-700 border-emerald-100",
    warn: "bg-amber-50 text-amber border-amber-100",
    error: "bg-red-50 text-coral border-red-100",
  };
  return (
    <span title={title} className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

/** A row of mutually exclusive choices (aria-pressed buttons in a labelled group). */
export function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex overflow-hidden rounded-lg border border-line bg-raised">
      {options.map((o, i) => (
        <button
          key={String(o.value)}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent-border ${
            i > 0 ? "border-l border-line" : ""
          } ${o.value === value ? "bg-accent text-white" : "text-ink-2 hover:text-accent"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={v}
      className="h-1.5 w-full overflow-hidden rounded-full bg-line-s"
    >
      <div className="h-full rounded-full bg-accent transition-all duration-500" style={{ width: `${v}%` }} />
    </div>
  );
}

export function errorMessage(e: unknown, fallback = "Something went wrong"): string {
  if (e instanceof Error) {
    // apiFetch throws "API 422: {json}": show the FastAPI detail when there is one.
    const m = /^API \d+: (\{.*\})$/s.exec(e.message);
    if (m) {
      try {
        const detail = JSON.parse(m[1]).detail;
        if (typeof detail === "string") return detail;
      } catch {
        /* fall through */
      }
    }
    return e.message || fallback;
  }
  return fallback;
}
