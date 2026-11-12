export type DotStatus = "ok" | "warn" | "error" | "off";

const COLORS: Record<DotStatus, string> = {
  ok: "bg-emerald-500",
  warn: "bg-amber-500",
  error: "bg-red-500",
  off: "bg-gray-300",
};

const LABELS: Record<DotStatus, string> = { ok: "ok", warn: "warning", error: "error", off: "off" };

/** A small coloured dot with a text alternative. */
export default function StatusDot({ status, className = "" }: { status: DotStatus; className?: string }) {
  return (
    <span
      role="img"
      aria-label={`status: ${LABELS[status]}`}
      data-status={status}
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${COLORS[status]} ${className}`}
    />
  );
}
