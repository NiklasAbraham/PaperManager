import type { T_IngestOut, ParsedMeta, GraphData, Reference } from "../types";

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

export async function ingestFromUrl(url: string, projectId?: string): Promise<T_IngestOut> {
  return apiFetch<T_IngestOut>("/papers/from-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, project_id: projectId ?? null }),
  });
}

export async function deletePaper(paperId: string): Promise<void> {
  const res = await fetch(`${BASE}/papers/${paperId}`, { method: "DELETE" });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Delete failed ${res.status}: ${detail}`);
  }
}

export async function updatePaper(paperId: string, data: Partial<{
  title: string; year: number | null; doi: string | null;
  abstract: string | null; summary: string | null;
}>): Promise<Paper> {
  return apiFetch<Paper>(`/papers/${paperId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function fetchGraph(mode: string): Promise<GraphData> {
  return apiFetch<GraphData>(`/graph?mode=${mode}`);
}

export async function extractReferences(paperId: string): Promise<{ references: Reference[] }> {
  return apiFetch(`/papers/${paperId}/extract-references`);
}

export async function saveReferences(paperId: string, references: Reference[]): Promise<void> {
  await apiFetch(`/papers/${paperId}/references`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ references }),
  });
}

// ── Entity management ─────────────────────────────────────────────────────────

export async function suggestTags(title: string, abstract?: string): Promise<{
  existing: string[]; new: string[]; all_tags: string[];
}> {
  return apiFetch("/tags/suggest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, abstract: abstract ?? null }),
  });
}

export async function applyTags(paperId: string, tags: string[]): Promise<void> {
  await Promise.all(tags.map((name) =>
    apiFetch(`/papers/${paperId}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    })
  ));
}

export async function createStandaloneTag(name: string): Promise<void> {
  await apiFetch(`/tags`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function deleteTag(name: string): Promise<void> {
  await apiFetch(`/tags/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export async function createStandaloneTopic(name: string): Promise<void> {
  await apiFetch(`/topics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function deleteTopic(name: string): Promise<void> {
  await apiFetch(`/topics/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export async function renameTopic(oldName: string, newName: string): Promise<void> {
  await apiFetch(`/topics/${encodeURIComponent(oldName)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: newName }),
  });
}

export async function deletePerson(personId: string): Promise<void> {
  await apiFetch(`/people/${personId}`, { method: "DELETE" });
}

export async function updatePerson(personId: string, data: { name?: string; affiliation?: string }): Promise<void> {
  await apiFetch(`/people/${personId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiFetch(`/projects/${projectId}`, { method: "DELETE" });
}

export async function updateProject(projectId: string, data: { name?: string; description?: string }): Promise<void> {
  await apiFetch(`/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function createTag(paperId: string, name: string): Promise<void> {
  await apiFetch(`/papers/${paperId}/tags`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function listReferences(
  paperId: string
): Promise<{ references: Reference[]; cited_by: Reference[] }> {
  return apiFetch(`/papers/${paperId}/references`);
}
