/** Number, money and time formatting shared by the Tokens, Reports, Suggestions and Health pages. */

/** `$12.40` from 1 dollar up, `$0.0123` below (three significant digits, at least two decimals). */
export function formatUsd(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  if (v === 0) return "$0.00";
  const a = Math.abs(v);
  if (a >= 1) return `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (a < 0.000001) return `<$0.000001`;
  let s = v.toPrecision(3);
  if (s.includes("e")) s = v.toFixed(6);
  const dot = s.indexOf(".");
  if (dot >= 0) {
    // Trim trailing zeros but keep two decimals.
    while (s.length - dot - 1 > 2 && s.endsWith("0")) s = s.slice(0, -1);
  }
  return `$${s}`;
}

/** Cost cell: "free" for a zero cost on LiteLLM, "unknown" without a price. */
export function formatCost(cost: number | null | undefined, provider?: string, priceKnown = true): string {
  if (cost === null || cost === undefined || !priceKnown) return "unknown";
  if (cost === 0 && provider === "litellm") return "free";
  return formatUsd(cost);
}

/** 950, 12.3k, 120k, 1.23M. */
export function formatTokens(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "0";
  const a = Math.abs(n);
  if (a < 1000) return String(Math.round(n));
  if (a < 1_000_000) {
    const k = n / 1000;
    return `${a >= 100_000 ? Math.round(k) : k.toFixed(1).replace(/\.0$/, "")}k`;
  }
  const m = n / 1_000_000;
  return `${a >= 100_000_000 ? Math.round(m) : m.toFixed(2).replace(/\.?0+$/, "")}M`;
}

export function formatInt(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString("en-US");
}

export function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  // A bare "2026-11-12" names a calendar day: keep it in local time so it does not shift in the west.
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (day) return new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]));
  // "2026-11-12 09:58:01" (no zone, no T) is read as UTC like the ledger's timestamps.
  const norm = /^\d{4}-\d{2}-\d{2} \d/.test(iso) ? `${iso.replace(" ", "T")}Z` : iso;
  const d = new Date(norm);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "12 Nov 2026". */
export function formatDate(iso: string | null | undefined): string {
  const d = parseDate(iso);
  return d ? d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";
}

/** "12 Nov, 09:58". */
export function formatDateTime(iso: string | null | undefined): string {
  const d = parseDate(iso);
  return d
    ? d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : "";
}

/** "5 min ago", "in 2 h", "just now". */
export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  const d = parseDate(iso);
  if (!d) return "never";
  const diff = (now - d.getTime()) / 1000;
  const a = Math.abs(diff);
  let v: string;
  if (a < 45) return "just now";
  if (a < 3600) v = `${Math.max(1, Math.round(a / 60))} min`;
  else if (a < 172800) v = `${Math.round(a / 3600)} h`;
  else v = `${Math.round(a / 86400)} d`;
  return diff >= 0 ? `${v} ago` : `in ${v}`;
}

/** 93784 -> "1 d 2 h", 3700 -> "1 h 1 min", 42 -> "42 s". */
export function formatUptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "n/a";
  const s = Math.max(0, Math.floor(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d} d ${h} h`;
  if (h > 0) return `${h} h ${m} min`;
  if (m > 0) return `${m} min`;
  return `${s} s`;
}

/** Interval in seconds as "10 min", "1 h", "30 s". */
export function formatInterval(seconds: number | null | undefined): string {
  if (!seconds) return "n/a";
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}
