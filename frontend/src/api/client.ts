import type { T_IngestOut, ParsedMeta, GraphData, Reference, Conversation, KnowledgeMessage, SseEvent, BulkSseEvent, Figure, Paper } from "../types";

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
  projectId?: string,
  captionMethod?: string,
  summaryInstructions?: string,
): Promise<T_IngestOut> {
  const form = new FormData();
  form.append("file", file);
  if (titleOverride) form.append("title_override", titleOverride);
  if (projectId) form.append("project_id", projectId);
  if (captionMethod) form.append("caption_method", captionMethod);
  if (summaryInstructions) form.append("summary_instructions", summaryInstructions);
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
  abstract: string | null; summary: string | null; venue: string | null;
  reading_status: string | null; rating: number | null;
  bookmarked: boolean | null; color: string | null;
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

export async function suggestTopics(paperId: string): Promise<{ topics: string[] }> {
  return apiFetch(`/papers/${paperId}/topics/suggest`, { method: "POST" });
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

export async function getOrCreatePerson(name: string): Promise<{id: string; name: string; affiliation?: string}> {
  return apiFetch("/people/get-or-create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, affiliation: "" }),
  });
}

export async function linkPersonInvolves(paperId: string, personId: string, role: string): Promise<void> {
  await apiFetch(`/papers/${paperId}/involves`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ person_id: personId, role }),
  });
}

export async function listPeople(): Promise<{id: string; name: string; affiliation?: string}[]> {
  return apiFetch("/people");
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

export async function removeAuthor(paperId: string, personId: string): Promise<void> {
  const res = await fetch(`${BASE}/papers/${paperId}/authors/${personId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Remove author failed ${res.status}`);
}

export async function listProjects(): Promise<{id: string; name: string; description?: string}[]> {
  return apiFetch("/projects");
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

// ── Knowledge Chat ────────────────────────────────────────────────────────────

export async function listConversations(): Promise<Conversation[]> {
  return apiFetch("/knowledge-chat/conversations");
}

export async function getConversationMessages(id: string): Promise<KnowledgeMessage[]> {
  return apiFetch(`/knowledge-chat/conversations/${id}/messages`);
}

export async function compactConversation(id: string): Promise<void> {
  await apiFetch(`/knowledge-chat/conversations/${id}/compact`, { method: "POST" });
}

export async function deleteConversation(id: string): Promise<void> {
  await apiFetch(`/knowledge-chat/conversations/${id}`, { method: "DELETE" });
}

export async function* streamKnowledgeChat(body: {
  question: string;
  history: { role: string; content: string }[];
  model: string;
  conversation_id?: string;
}): AsyncGenerator<SseEvent> {
  const res = await fetch(`${BASE}/knowledge-chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) throw new Error(`API ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6)) as SseEvent;
        } catch { /* skip malformed */ }
      }
    }
  }
}

// ── Bulk import ───────────────────────────────────────────────────────────────

export async function* bulkImport(
  body: { papers: object[]; project_id?: string | null; fetch_pdf?: boolean },
  signal?: AbortSignal,
): AsyncGenerator<BulkSseEvent> {
  const res = await fetch(`${BASE}/papers/bulk-import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`API ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6)) as BulkSseEvent;
        } catch { /* skip malformed */ }
      }
    }
  }
}

// ── Figures ───────────────────────────────────────────────────────────────────

export async function fetchFigures(paperId: string): Promise<Figure[]> {
  return apiFetch(`/papers/${paperId}/figures`);
}

export async function extractFiguresForPaper(
  paperId: string,
  captionMethod = "ollama",
): Promise<{ extracted: number }> {
  return apiFetch(`/papers/${paperId}/figures/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ caption_method: captionMethod }),
  });
}

export async function chatWithFigure(
  paperId: string,
  figureId: string,
  question: string,
  model = "claude",
): Promise<{ answer: string }> {
  return apiFetch(`/papers/${paperId}/figures/${figureId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, model }),
  });
}
