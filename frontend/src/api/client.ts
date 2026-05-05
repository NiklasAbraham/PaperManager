import type { T_IngestOut, ParsedMeta, GraphData, Reference, Conversation, KnowledgeMessage, SseEvent, BulkSseEvent, Figure, LiteratureSseEvent, Paper, Chapter, Blog, BlogPost, Note, Annotation, AnnotationColor } from "../types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

function userHeader(): Record<string, string> {
  const name = localStorage.getItem("pm_current_user");
  return name ? { "X-User-Name": name } : {};
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const merged: RequestInit = {
    ...options,
    headers: {
      ...userHeader(),
      ...(options?.headers ?? {}),
    },
  };
  const res = await fetch(`${BASE}${path}`, merged);
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
  debug?: boolean,
  documentType?: string,
): Promise<T_IngestOut> {
  const form = new FormData();
  form.append("file", file);
  if (titleOverride) form.append("title_override", titleOverride);
  if (projectId) form.append("project_id", projectId);
  if (captionMethod) form.append("caption_method", captionMethod);
  if (summaryInstructions) form.append("summary_instructions", summaryInstructions);
  if (debug) form.append("debug", "true");
  if (documentType) form.append("document_type", documentType);
  const res = await fetch(`${BASE}/papers/upload`, { method: "POST", body: form, headers: userHeader() });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Upload failed ${res.status}: ${detail}`);
  }
  return res.json();
}

export async function previewUrl(url: string): Promise<ParsedMeta> {
  return apiFetch<ParsedMeta>("/papers/preview-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
}

export async function previewUrlPdf(url: string): Promise<ParsedMeta> {
  return apiFetch<ParsedMeta>("/papers/preview-url/pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
}

export async function ingestFromUrl(url: string, projectId?: string, debug?: boolean): Promise<T_IngestOut> {
  return apiFetch<T_IngestOut>("/papers/from-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, project_id: projectId ?? null, debug: debug ?? false }),
  });
}

export async function ingestFromUrlFull(url: string, projectId?: string, debug?: boolean, summaryInstructions?: string): Promise<T_IngestOut> {
  return apiFetch<T_IngestOut>("/papers/from-url-full", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, project_id: projectId ?? null, debug: debug ?? false, summary_instructions: summaryInstructions ?? null }),
  });
}

export async function deleteDebugPapers(): Promise<{ deleted: number; figures_deleted: number }> {
  return apiFetch("/papers/debug-cleanup", { method: "DELETE" });
}

export async function countDebugPapers(): Promise<number> {
  const res = await apiFetch<unknown[]>("/search?tag=debug&limit=500");
  return Array.isArray(res) ? res.length : 0;
}

export async function exportRdf(): Promise<void> {
  const res = await fetch(`${BASE}/export/rdf`);
  if (!res.ok) throw new Error(`Export failed ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "papermanager.ttl"; a.click();
  URL.revokeObjectURL(url);
}

export async function exportCsv(): Promise<void> {
  const res = await fetch(`${BASE}/export/csv`);
  if (!res.ok) throw new Error(`Export failed ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "papermanager_export.zip"; a.click();
  URL.revokeObjectURL(url);
}

export async function importRdf(file: File): Promise<{ imported: Record<string, number> }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/export/import/rdf`, { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Import failed ${res.status}: ${detail}`);
  }
  return res.json();
}

export async function clearPapers(): Promise<Record<string, number>> {
  return apiFetch("/admin/clear-papers", { method: "DELETE" });
}

export async function seedDefaults(): Promise<{ seeded: number }> {
  return apiFetch("/admin/seed-defaults", { method: "POST" });
}

export async function regenerateSummary(paperId: string): Promise<{ summary: string }> {
  return apiFetch(`/papers/${paperId}/regenerate-summary`, { method: "POST" });
}

export async function reextractAbstract(paperId: string): Promise<{ abstract: string }> {
  return apiFetch(`/papers/${paperId}/reextract-abstract`, { method: "POST" });
}

export async function reextractMetadata(paperId: string): Promise<{
  title?: string; authors?: string[]; year?: number | null;
  doi?: string | null; venue?: string | null; abstract?: string | null;
  metadata_source?: string;
}> {
  return apiFetch(`/papers/${paperId}/reextract-metadata`, { method: "POST" });
}

export async function refetchPdf(paperId: string): Promise<{ authors: string[]; drive_url?: string }> {
  return apiFetch(`/papers/${paperId}/refetch-pdf`, { method: "POST" });
}

export async function uploadPdfForPaper(paperId: string, file: File): Promise<{ drive_url?: string; authors_added: string[]; raw_text_len: number }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/papers/${paperId}/upload-pdf`, { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`PDF upload failed ${res.status}: ${detail}`);
  }
  return res.json();
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
  metadata_source: string | null;
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

export async function getOrCreatePerson(name: string, affiliation?: string, email?: string): Promise<{id: string; name: string; affiliation?: string; email?: string}> {
  return apiFetch("/people/get-or-create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, affiliation: affiliation ?? null, email: email ?? null }),
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

export async function fetchPaperInvolves(paperId: string): Promise<{id: string; name: string; affiliation?: string; role: string}[]> {
  return apiFetch(`/papers/${paperId}/involves`);
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

export async function fetchPaperProjects(paperId: string): Promise<{id: string; name: string; description?: string; status?: string}[]> {
  return apiFetch(`/papers/${paperId}/projects`);
}

export async function listProjects(): Promise<{id: string; name: string; description?: string; status?: string}[]> {
  return apiFetch("/projects");
}

export async function getProject(projectId: string): Promise<{id: string; name: string; description?: string; status?: string; papers: object[]}> {
  return apiFetch(`/projects/${projectId}`);
}

export async function createProject(data: { name: string; description?: string; status?: string }): Promise<{id: string; name: string}> {
  return apiFetch("/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiFetch(`/projects/${projectId}`, { method: "DELETE" });
}

export async function updateProject(projectId: string, data: { name?: string; description?: string; status?: string }): Promise<void> {
  await apiFetch(`/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function removePaperFromProject(projectId: string, paperId: string): Promise<void> {
  await apiFetch(`/projects/${projectId}/papers/${paperId}`, { method: "DELETE" });
}

export async function addPaperToProject(projectId: string, paperId: string): Promise<void> {
  await apiFetch(`/projects/${projectId}/papers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paper_id: paperId }),
  });
}

export async function getProjectTags(projectId: string): Promise<{ name: string; count: number; paper_ids: string[] }[]> {
  return apiFetch(`/projects/${projectId}/tags`);
}

export async function getProjectNote(projectId: string): Promise<{ content: string }> {
  return apiFetch(`/projects/${projectId}/note`);
}

export async function saveProjectNote(projectId: string, content: string): Promise<{ content: string }> {
  return apiFetch(`/projects/${projectId}/note`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export async function getProjectKeywords(projectId: string): Promise<{ content: string }> {
  return apiFetch(`/projects/${projectId}/keywords`);
}

export async function saveProjectKeywords(projectId: string, content: string): Promise<{ content: string }> {
  return apiFetch(`/projects/${projectId}/keywords`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export function projectBibtexUrl(projectId: string): string {
  return `${BASE}/projects/${projectId}/export/bibtex`;
}

export function projectCsvUrl(projectId: string): string {
  return `${BASE}/projects/${projectId}/export/csv`;
}

export function projectConversationsUrl(projectId: string): string {
  return `${BASE}/projects/${projectId}/export/conversations`;
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

// ── Per-paper conversations ───────────────────────────────────────────────────

export async function listPaperConversations(paperId: string): Promise<import("../types").Conversation[]> {
  return apiFetch(`/papers/${paperId}/conversations`);
}

export async function getPaperConversationMessages(paperId: string, convId: string): Promise<import("../types").KnowledgeMessage[]> {
  return apiFetch(`/papers/${paperId}/conversations/${convId}/messages`);
}

export async function renamePaperConversation(paperId: string, convId: string, title: string): Promise<void> {
  await apiFetch(`/papers/${paperId}/conversations/${convId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export async function compactPaperConversation(paperId: string, convId: string): Promise<void> {
  await apiFetch(`/papers/${paperId}/conversations/${convId}/compact`, { method: "POST" });
}

export async function deletePaperConversation(paperId: string, convId: string): Promise<void> {
  await apiFetch(`/papers/${paperId}/conversations/${convId}`, { method: "DELETE" });
}

export async function chatWithPaper(
  paperId: string,
  question: string,
  history: { role: string; content: string }[],
  model: string,
  conversationId?: string,
): Promise<{ answer: string; conversation_id: string }> {
  return apiFetch(`/papers/${paperId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history, model, conversation_id: conversationId ?? null }),
  });
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

// ── Literature keywords ───────────────────────────────────────────────────────

export async function getLiteratureKeywords(): Promise<{ content: string }> {
  return apiFetch("/literature/keywords");
}

export async function putLiteratureKeywords(content: string): Promise<{ content: string; keywords: string[] }> {
  return apiFetch("/literature/keywords", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

// ── Literature search ─────────────────────────────────────────────────────────

export async function* searchLiterature(
  body: { days: number; max_per_source: number; sources: string[]; project_id?: string | null },
  signal?: AbortSignal,
): AsyncGenerator<LiteratureSseEvent> {
  const res = await fetch(`${BASE}/literature/search`, {
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
          yield JSON.parse(line.slice(6)) as LiteratureSseEvent;
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

// ── Chapters (book support) ───────────────────────────────────────────────────

export async function listChapters(paperId: string): Promise<Chapter[]> {
  return apiFetch<Chapter[]>(`/papers/${paperId}/chapters`);
}

export async function detectChapters(paperId: string, useAi = false, model?: string): Promise<Chapter[]> {
  return apiFetch<Chapter[]>(`/papers/${paperId}/chapters/detect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ use_ai: useAi, model: model || null }),
  });
}

export async function regenerateChapterSummary(paperId: string, chapterId: string, model?: string): Promise<Chapter> {
  return apiFetch<Chapter>(`/papers/${paperId}/chapters/${chapterId}/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: model || null }),
  });
}

export async function listOllamaModels(): Promise<string[]> {
  return apiFetch<string[]>("/ollama/models");
}

export async function chatWithChapter(
  paperId: string,
  chapterId: string,
  question: string,
  history: { role: string; content: string }[] = [],
): Promise<{ answer: string }> {
  return apiFetch(`/papers/${paperId}/chapters/${chapterId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  });
}

/**
 * Returns the URL for a chapter's PDF slice.
 * The URL can be used directly as an iframe src or anchor href.
 */
export function getChapterPdfUrl(paperId: string, chapterId: string): string {
  return `${BASE}/papers/${paperId}/chapters/${chapterId}/pdf`;
}

/**
 * Returns the URL for the full book PDF.
 */
export function getPaperPdfUrl(paperId: string): string {
  return `${BASE}/papers/${paperId}/pdf`;
}

// ── Blogs ─────────────────────────────────────────────────────────────────────

export function listBlogs(): Promise<Blog[]> {
  return apiFetch("/blogs");
}

export function registerBlog(url: string): Promise<Blog> {
  return apiFetch("/blogs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
}

export function deleteBlog(blogId: string): Promise<void> {
  return apiFetch(`/blogs/${blogId}`, { method: "DELETE" });
}

export function fetchBlogPosts(blogId: string): Promise<{ new_posts: number; total_fetched: number }> {
  return apiFetch(`/blogs/${blogId}/fetch`, { method: "POST" });
}

export function listBlogPosts(blogId: string, status?: string): Promise<BlogPost[]> {
  const qs = status ? `?status=${status}` : "";
  return apiFetch(`/blogs/${blogId}/posts${qs}`);
}

export function getRandomBlogPost(status = "unread"): Promise<BlogPost> {
  return apiFetch(`/blogs/posts/random?status=${status}`);
}

export function getBlogPost(postId: string): Promise<BlogPost> {
  return apiFetch(`/blogs/posts/${postId}`);
}

export function updateBlogPost(postId: string, data: { reading_status?: string }): Promise<BlogPost> {
  return apiFetch(`/blogs/posts/${postId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function deleteBlogPost(postId: string): Promise<void> {
  return apiFetch(`/blogs/posts/${postId}`, { method: "DELETE" });
}

export function importBlogPost(postId: string): Promise<{ imported: boolean; content_length: number }> {
  return apiFetch(`/blogs/posts/${postId}/import`, { method: "POST" });
}

export function summarizeBlogPost(postId: string): Promise<{ summary: string; post: BlogPost }> {
  return apiFetch(`/blogs/posts/${postId}/summarize`, { method: "POST" });
}

export function chatWithBlogPost(
  postId: string,
  question: string,
  history: { role: string; content: string }[] = [],
): Promise<{ answer: string }> {
  return apiFetch(`/blogs/posts/${postId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  });
}

export function getBlogPostNote(postId: string): Promise<Note> {
  return apiFetch(`/blogs/posts/${postId}/note`);
}

export function saveBlogPostNote(postId: string, content: string): Promise<Note> {
  return apiFetch(`/blogs/posts/${postId}/note`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

// ── Blog post tags ─────────────────────────────────────────────────────────────

export function getBlogPostTags(postId: string): Promise<{ id: string; name: string }[]> {
  return apiFetch(`/blogs/posts/${postId}/tags`);
}

export function addBlogPostTag(postId: string, tagName: string): Promise<{ id: string; name: string }> {
  return apiFetch(`/blogs/posts/${postId}/tags/${encodeURIComponent(tagName)}`, { method: "POST" });
}

export function removeBlogPostTag(postId: string, tagName: string): Promise<void> {
  return apiFetch(`/blogs/posts/${postId}/tags/${encodeURIComponent(tagName)}`, { method: "DELETE" });
}

// ── Blog post people ───────────────────────────────────────────────────────────

export function getBlogPostPeople(postId: string): Promise<{ id: string; name: string; role: string }[]> {
  return apiFetch(`/blogs/posts/${postId}/people`);
}

export function linkPersonToBlogPost(postId: string, name: string, role = "author"): Promise<{ id: string; name: string }> {
  return apiFetch(`/blogs/posts/${postId}/people`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, role }),
  });
}

export function unlinkPersonFromBlogPost(postId: string, personId: string): Promise<void> {
  return apiFetch(`/blogs/posts/${postId}/people/${personId}`, { method: "DELETE" });
}

// ── Blog post projects ─────────────────────────────────────────────────────────

export function getBlogPostProjects(postId: string): Promise<{ id: string; name: string }[]> {
  return apiFetch(`/blogs/posts/${postId}/projects`);
}

export function addBlogPostToProject(postId: string, projectId: string): Promise<{ ok: boolean }> {
  return apiFetch(`/blogs/posts/${postId}/projects/${projectId}`, { method: "POST" });
}

export function removeBlogPostFromProject(postId: string, projectId: string): Promise<void> {
  return apiFetch(`/blogs/posts/${postId}/projects/${projectId}`, { method: "DELETE" });
}

// ── Blog reimport ──────────────────────────────────────────────────────────────

export function reimportAllBlogPosts(blogId: string): Promise<{ updated: number; errors: number }> {
  return apiFetch(`/blogs/${blogId}/reimport-all`, { method: "POST" });
}

// ── Annotations ───────────────────────────────────────────────────────────────

export function listAnnotations(paperId: string): Promise<Annotation[]> {
  return apiFetch<Annotation[]>(`/papers/${paperId}/annotations`);
}

export function createAnnotation(
  paperId: string,
  body: {
    page_number: number;
    highlighted_text: string;
    color: AnnotationColor;
    note: string;
    position_json: string;
  },
): Promise<Annotation> {
  return apiFetch<Annotation>(`/papers/${paperId}/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateAnnotation(
  paperId: string,
  annotationId: string,
  body: { note?: string; color?: AnnotationColor },
): Promise<Annotation> {
  return apiFetch<Annotation>(`/papers/${paperId}/annotations/${annotationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteAnnotation(paperId: string, annotationId: string): Promise<void> {
  const res = await fetch(`${BASE}/papers/${paperId}/annotations/${annotationId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Delete annotation failed ${res.status}`);
}

// ── Discover (external search) ────────────────────────────────────────────────

export async function discoverSearch(
  q: string,
  source: string = "all",
  limit: number = 20,
): Promise<import("../types").DiscoverSearchResult[]> {
  return apiFetch(`/discover/search?q=${encodeURIComponent(q)}&source=${source}&limit=${limit}`);
}

export async function discoverAdd(url: string, projectId?: string): Promise<T_IngestOut> {
  return apiFetch("/discover/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, project_id: projectId ?? null }),
  });
}

// ── Related papers ────────────────────────────────────────────────────────────

export async function getRelatedPapers(
  paperId: string,
  limit: number = 10,
): Promise<{ related: import("../types").RelatedPaper[]; reason?: string }> {
  return apiFetch(`/papers/${paperId}/related?limit=${limit}`);
}
