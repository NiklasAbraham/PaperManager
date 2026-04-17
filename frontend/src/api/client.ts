import type { T_IngestOut, ParsedMeta } from "../types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json();
}

export async function parsePdf(file: File): Promise<ParsedMeta> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/papers/parse`, { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Parse failed ${res.status}: ${detail}`);
  }
  return res.json();
}

export async function uploadPdf(
  file: File,
  titleOverride?: string,
  projectId?: string
): Promise<T_IngestOut> {
  const form = new FormData();
  form.append("file", file);
  if (titleOverride) form.append("title_override", titleOverride);
  if (projectId) form.append("project_id", projectId);
  const res = await fetch(`${BASE}/papers/upload`, { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Upload failed ${res.status}: ${detail}`);
  }
  return res.json();
}
