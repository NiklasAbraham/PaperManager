export function formatCellValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v, null, 0).slice(0, 120);
  return String(v);
}

export function isMutation(counters: Record<string, number>): boolean {
  return Object.values(counters).some((n) => n > 0);
}
