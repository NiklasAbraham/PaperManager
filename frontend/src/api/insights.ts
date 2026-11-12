/**
 * Typed API for the four "insights" pages: token ledger, reports, suggestions, system health.
 * Response shapes mirror .specs/013_tokens.md, 014_reports.md, 015_suggestions.md, 016_health.md.
 */
import { apiFetch } from "./client";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

type Query = Record<string, string | number | boolean | null | undefined>;

/** `?a=1&b=2`, leaving out undefined, null and empty values. */
function qs(params?: Query): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

const JSON_HEADERS = { "Content-Type": "application/json" };

/** DELETE endpoints answer 204 with no body, which apiFetch cannot parse: use fetch directly. */
async function deleteRequest(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE", credentials: "include" });
  if (res.status === 401) {
    localStorage.removeItem("pm_username");
    localStorage.removeItem("pm_current_user");
    window.dispatchEvent(new CustomEvent("auth:expired"));
    throw new Error("Session expired. Please login again.");
  }
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
}

// ── Tokens ────────────────────────────────────────────────────────────────────

export interface TokenTotals {
  calls: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number;
  billed_usd: number;
  subscription_usd: number;
  unknown_price_calls: number;
}

export interface TokenToday {
  calls: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface TokenDayRow {
  day: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface TokenWeekRow {
  week: string;
  start: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface TokenFeatureRow {
  feature: string;
  calls: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  avg_latency_ms: number;
}

export interface TokenModelRow {
  model: string;
  provider: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  price_known: boolean;
}

export interface TokenProviderRow {
  provider: string;
  calls: number;
  cost_usd: number;
}

export interface TokenUserRow {
  user: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface TokenCallRow {
  id: number;
  ts: string;
  feature: string;
  label: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number | null;
  price_known: boolean;
  user: string | null;
  paper_id: string | null;
  ok: boolean;
  error: string | null;
  latency_ms: number;
  streamed: boolean;
  estimated: boolean;
}

export interface TokenPaperRow {
  paper_id: string;
  title: string | null;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface TokenSummary {
  range: { since: string; until: string; days: number };
  scope: { user: string | null; is_admin: boolean };
  totals: TokenTotals;
  today: TokenToday;
  by_day: TokenDayRow[];
  by_week: TokenWeekRow[];
  by_feature: TokenFeatureRow[];
  by_model: TokenModelRow[];
  by_provider: TokenProviderRow[];
  by_user: TokenUserRow[];
  top_calls: TokenCallRow[];
  top_papers: TokenPaperRow[];
  unknown_models: string[];
  prices_as_of: string;
}

export interface TokenSummaryParams {
  days?: number;
  user?: string;
  feature?: string;
  model?: string;
}

export interface TokenCallsParams {
  limit?: number;
  offset?: number;
  user?: string;
  feature?: string;
  model?: string;
  provider?: string;
  paper_id?: string;
  ok?: boolean;
  days?: number;
}

export interface TokenCallsResponse {
  calls: TokenCallRow[];
  total: number;
}

export interface TokenPrices {
  as_of: string;
  litellm_free: boolean;
  models: { prefix: string; input: number; output: number; cache_write: number; cache_read: number }[];
}

export function getTokenSummary(params: TokenSummaryParams = {}): Promise<TokenSummary> {
  return apiFetch<TokenSummary>(`/tokens/summary${qs({ ...params })}`);
}

export function getTokenCalls(params: TokenCallsParams = {}): Promise<TokenCallsResponse> {
  return apiFetch<TokenCallsResponse>(`/tokens/calls${qs({ ...params })}`);
}

export function getTokenPrices(): Promise<TokenPrices> {
  return apiFetch<TokenPrices>("/tokens/prices");
}

// ── Reports ───────────────────────────────────────────────────────────────────

export type ReportStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export type ReportLength = "short" | "standard" | "long";

export interface ReportOptions {
  models: { id: string; label: string; available: boolean }[];
  lengths: ReportLength[];
  default_model: string;
}

export interface ReportCreateBody {
  question?: string;
  project_id?: string;
  paper_ids?: string[];
  length?: ReportLength;
  model?: string;
}

export interface ReportSummary {
  id: string;
  title: string | null;
  question: string | null;
  project_id: string | null;
  project_name: string | null;
  status: ReportStatus;
  stage: string | null;
  progress: number;
  model: string;
  length: ReportLength;
  owner: string;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  paper_count: number;
  word_count: number;
  error: string | null;
}

export interface ReportStep {
  ts: string;
  message: string;
}

export interface ReportPaper {
  id: string;
  title: string;
  year: number | null;
  n: number;
}

export interface ReportDetail extends ReportSummary {
  markdown: string | null;
  steps: ReportStep[];
  papers: ReportPaper[];
}

export function getReportOptions(): Promise<ReportOptions> {
  return apiFetch<ReportOptions>("/reports/options");
}

export function createReport(body: ReportCreateBody): Promise<ReportSummary> {
  return apiFetch<ReportSummary>("/reports", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function listReports(all = false): Promise<ReportSummary[]> {
  return apiFetch<ReportSummary[]>(`/reports${qs({ all: all ? "true" : undefined })}`);
}

export function getReport(id: string): Promise<ReportDetail> {
  return apiFetch<ReportDetail>(`/reports/${encodeURIComponent(id)}`);
}

export function cancelReport(id: string): Promise<ReportSummary> {
  return apiFetch<ReportSummary>(`/reports/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

export function deleteReport(id: string): Promise<void> {
  return deleteRequest(`/reports/${encodeURIComponent(id)}`);
}

/** Fetches the export and saves it through an object URL; the filename comes from Content-Disposition. */
export async function downloadReport(id: string, format: "md" | "html"): Promise<void> {
  const res = await fetch(`${BASE}/reports/${encodeURIComponent(id)}/export?format=${format}`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  const cd = res.headers.get("Content-Disposition") ?? "";
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  let filename = `report-${id}.${format}`;
  if (m) {
    try {
      filename = decodeURIComponent(m[1]);
    } catch {
      filename = m[1];
    }
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ── Suggestions ───────────────────────────────────────────────────────────────

export type SuggestionSource = "chat" | "user" | "report";
export type SuggestionStatus = "open" | "planned" | "done" | "dismissed";

export interface SuggestionOut {
  id: string;
  text: string;
  detail: string | null;
  source: SuggestionSource;
  status: SuggestionStatus;
  created_by: string;
  created_at: string;
  updated_at: string;
  votes: number;
  voted: boolean;
  context: string | null;
  conversation_id: string | null;
  seen: number;
}

export type SuggestionCounts = Record<SuggestionStatus, number>;

export interface SuggestionListParams {
  status?: SuggestionStatus;
  source?: SuggestionSource;
  sort?: "votes" | "new";
}

export interface SuggestionCreateBody {
  text: string;
  detail?: string;
}

export interface SuggestionUpdateBody {
  status?: SuggestionStatus;
  text?: string;
  detail?: string;
}

export function listSuggestions(params: SuggestionListParams = {}): Promise<SuggestionOut[]> {
  return apiFetch<SuggestionOut[]>(`/suggestions${qs({ ...params })}`);
}

export function getSuggestionCounts(): Promise<SuggestionCounts> {
  return apiFetch<SuggestionCounts>("/suggestions/counts");
}

export function createSuggestion(body: SuggestionCreateBody): Promise<SuggestionOut> {
  return apiFetch<SuggestionOut>("/suggestions", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function updateSuggestion(id: string, body: SuggestionUpdateBody): Promise<SuggestionOut> {
  return apiFetch<SuggestionOut>(`/suggestions/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function voteSuggestion(id: string): Promise<SuggestionOut> {
  return apiFetch<SuggestionOut>(`/suggestions/${encodeURIComponent(id)}/vote`, { method: "POST" });
}

export function deleteSuggestion(id: string): Promise<void> {
  return deleteRequest(`/suggestions/${encodeURIComponent(id)}`);
}

// ── System health ─────────────────────────────────────────────────────────────

export type HealthStatus = "ok" | "warn" | "error" | "off";
export type OverallHealth = "ok" | "degraded" | "error";

export interface HealthCheck {
  id: string;
  label: string;
  status: HealthStatus;
  summary: string;
  details: Record<string, unknown> | null;
  checked_at: string;
  latency_ms: number | null;
}

export interface HealthSweeper {
  name: string;
  alive: boolean;
  last_run: string | null;
  last_ok: boolean | null;
  last_error: string | null;
  interval_s: number | null;
}

export interface HealthRecentError {
  ts: string;
  logger: string;
  level: string;
  message: string;
}

export interface HealthAuditEntry {
  ts: string;
  username: string;
  action_type: string;
  entity_type: string;
}

export interface SystemHealth {
  generated_at: string;
  status: OverallHealth;
  checks: HealthCheck[];
  version: {
    app: string;
    git_sha: string | null;
    git_branch: string | null;
    python: string;
    started_at: string;
    uptime_s: number;
  };
  tokens_today: TokenToday;
  recent_errors: HealthRecentError[];
  sweepers: HealthSweeper[];
  audit: { actions_24h: number; last: HealthAuditEntry[] };
}

export function getSystemHealth(refresh = false): Promise<SystemHealth> {
  return apiFetch<SystemHealth>(`/system/health${qs({ refresh: refresh ? "true" : undefined })}`);
}
