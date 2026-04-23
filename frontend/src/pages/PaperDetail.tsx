import { useEffect, useRef, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { apiFetch, extractReferences, saveReferences, listReferences, ingestFromUrl, suggestTags, applyTags, createStandaloneTag, suggestTopics, fetchFigures, extractFiguresForPaper, chatWithFigure, deletePaper, removeAuthor, fetchGraph, fetchPaperInvolves, regenerateSummary, updatePaper, refetchPdf } from "../api/client";
import NoteEditor from "../components/NoteEditor";
import ChatPanel from "../components/ChatPanel";
import EditPaperModal from "../components/EditPaperModal";
import BookChapters from "../components/BookChapters";
import { useAppSettings } from "../contexts/SettingsContext";
import type { Paper, Person, Topic, Tag, Reference, Figure, GraphData } from "../types";

const PAPER_GRAPH_NODE_COLORS: Record<string, string> = {
  paper: "#7c3aed", person: "#2563eb", topic: "#16a34a",
  tag: "#d97706", project: "#db2777", note: "#6b7280", unknown: "#9ca3af",
};

interface PaperFull extends Paper {
  authors?: Person[];
  topics?: Topic[];
  tags?: Tag[];
}

type RightTab = "notes" | "chat" | "references";

export default function PaperDetail() {
  const { id } = useParams<{ id: string }>();
  const [paper, setPaper]     = useState<PaperFull | null>(null);
  const [authors, setAuthors] = useState<Person[]>([]);
  const [topics, setTopics]   = useState<Topic[]>([]);
  const [tags, setTags]       = useState<Tag[]>([]);
  const [newTag, setNewTag]   = useState("");
  const [newTopic, setNewTopic] = useState("");
  const [tab, setTab]           = useState<RightTab>("notes");
  const [leftTab, setLeftTab]   = useState<"abstract" | "pdf" | "figures" | "chapters" | "graph" | "people" | "meta">("abstract");
  // Figures
  const [figures, setFigures]         = useState<Figure[]>([]);
  const [figuresLoaded, setFiguresLoaded] = useState(false);
  const [figuresExtracting, setFiguresExtracting] = useState(false);
  const [figuresExtractStep, setFiguresExtractStep] = useState(0);
  const [selectedFigure, setSelectedFigure] = useState<Figure | null>(null);
  const [figureQuestion, setFigureQuestion] = useState("");
  const [figureAnswer, setFigureAnswer]     = useState<string | null>(null);
  const [figureAnswering, setFigureAnswering] = useState(false);
  const [figureModel, setFigureModel]       = useState<"claude" | "claude-work">("claude");
  // Graph tab
  const [graphData, setGraphData]   = useState<GraphData | null>(null);
  const [graphLoaded, setGraphLoaded] = useState(false);
  const graphContainerRef = useRef<HTMLDivElement>(null);
  const graphInstanceRef  = useRef<unknown>(null);

  // People tab
  const [involves, setInvolves] = useState<{id: string; name: string; affiliation?: string; role: string}[]>([]);
  const [involvesLoaded, setInvolvesLoaded] = useState(false);

  const { settings } = useAppSettings();
  const [rightWidth, setRightWidth] = useState(320);
  const dragging = useRef(false);
  const [references, setReferences] = useState<Reference[]>([]);
  const [citedBy, setCitedBy]       = useState<Reference[]>([]);
  const [extracting, setExtracting]     = useState(false);
  const [pendingRefs, setPendingRefs]   = useState<Reference[] | null>(null);
  const [checkedRefs, setCheckedRefs]   = useState<boolean[]>([]);
  const [pullingDoi, setPullingDoi]     = useState<string | null>(null);
  const [suggestingTags, setSuggestingTags] = useState(false);
  const [suggestedExisting, setSuggestedExisting] = useState<string[]>([]);
  const [suggestedNew, setSuggestedNew]     = useState<string[]>([]);
  const [allTagSuggestions, setAllTagSuggestions] = useState<string[]>([]);
  const [selectedSugTags, setSelectedSugTags]     = useState<Set<string>>(new Set());
  const [newTagDraft, setNewTagDraft] = useState("");
  const [tagSuggestOpen, setTagSuggestOpen] = useState(false);
  const [suggestingTopics, setSuggestingTopics] = useState(false);
  const [suggestedTopics, setSuggestedTopics] = useState<string[]>([]);
  const [selectedSugTopics, setSelectedSugTopics] = useState<Set<string>>(new Set());
  const [topicSuggestOpen, setTopicSuggestOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (!id) return;
    apiFetch<PaperFull>(`/papers/${id}`).then(setPaper).catch(() => {});
    apiFetch<Person[]>(`/papers/${id}/authors`).then(setAuthors).catch(() => {});
    apiFetch<Topic[]>(`/papers/${id}/topics`).then(setTopics).catch(() => {});
    apiFetch<Tag[]>(`/papers/${id}/tags`).then(setTags).catch(() => {});
    listReferences(id)
      .then(({ references, cited_by }) => { setReferences(references); setCitedBy(cited_by); })
      .catch(() => {});
  }, [id]);

  // Load figures lazily when left tab is first opened
  useEffect(() => {
    if (leftTab === "figures" && id && !figuresLoaded) {
      fetchFigures(id).then((figs) => { setFigures(figs); setFiguresLoaded(true); }).catch(() => setFiguresLoaded(true));
    }
  }, [leftTab, id, figuresLoaded]);

  // Load involves lazily when people tab is first opened
  useEffect(() => {
    if (leftTab === "people" && id && !involvesLoaded) {
      fetchPaperInvolves(id).then((data) => { setInvolves(data); setInvolvesLoaded(true); }).catch(() => setInvolvesLoaded(true));
    }
  }, [leftTab, id, involvesLoaded]);

  // Load graph lazily when graph tab is first opened
  useEffect(() => {
    if (leftTab === "graph" && id && !graphLoaded) {
      fetchGraph(`paper&id=${id}`).then((data) => { setGraphData(data); setGraphLoaded(true); }).catch(() => setGraphLoaded(true));
    }
  }, [leftTab, id, graphLoaded]);

  // Build force-graph when graph data is ready
  useEffect(() => {
    if (!graphLoaded || !graphData || graphData.nodes.length === 0 || !graphContainerRef.current) return;

    import("force-graph").then(({ default: ForceGraph }) => {
      if (graphInstanceRef.current) {
        (graphInstanceRef.current as { _destructor?: () => void })?._destructor?.();
        if (graphContainerRef.current) graphContainerRef.current.innerHTML = "";
      }
      if (!graphContainerRef.current) return;

      const w = graphContainerRef.current.clientWidth;
      const h = graphContainerRef.current.clientHeight;

      const graph = ForceGraph()(graphContainerRef.current)
        .width(w)
        .height(h)
        .backgroundColor("#f9fafb")
        .nodeId("id")
        .nodeLabel((n: unknown) => (n as { label?: string }).label ?? "")
        .nodeColor((n: unknown) => PAPER_GRAPH_NODE_COLORS[(n as { type?: string }).type ?? "unknown"] ?? PAPER_GRAPH_NODE_COLORS.unknown)
        .nodeRelSize(6)
        .nodeCanvasObjectMode(() => "after")
        .nodeCanvasObject((node: unknown, ctx: CanvasRenderingContext2D, globalScale: number) => {
          const n = node as { label?: string; x?: number; y?: number };
          if (!n.label || typeof n.x !== "number" || typeof n.y !== "number") return;
          const fontSize = Math.max(10 / globalScale, 2.5);
          ctx.font = `${fontSize}px Inter, sans-serif`;
          const display = n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label;
          const tw = ctx.measureText(display).width;
          const px = n.x, py = n.y + 6 + fontSize * 0.9;
          ctx.fillStyle = "rgba(249,250,251,0.85)";
          ctx.fillRect(px - tw / 2 - 2, py - fontSize / 2 - 1, tw + 4, fontSize + 2);
          ctx.fillStyle = "#1e293b";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(display, px, py);
        })
        .linkColor(() => "#cbd5e1")
        .linkWidth(1.5)
        .linkDirectionalArrowLength(6)
        .linkDirectionalArrowRelPos(1)
        .linkCanvasObjectMode(() => "after")
        .linkCanvasObject((link: unknown, ctx: CanvasRenderingContext2D, globalScale: number) => {
          const l = link as { type?: string; source?: { x?: number; y?: number }; target?: { x?: number; y?: number } };
          const label = l.type ?? "";
          if (!label) return;
          const src = l.source, tgt = l.target;
          if (!src || !tgt || typeof src.x !== "number" || typeof tgt.x !== "number") return;
          const midX = (src.x! + tgt.x!) / 2;
          const midY = (src.y! + tgt.y!) / 2;
          const fontSize = Math.max(9 / globalScale, 2);
          ctx.font = `${fontSize}px Inter, sans-serif`;
          const tw = ctx.measureText(label).width;
          ctx.fillStyle = "rgba(249,250,251,0.85)";
          ctx.fillRect(midX - tw / 2 - 2, midY - fontSize / 2 - 1, tw + 4, fontSize + 2);
          ctx.fillStyle = "#64748b";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(label, midX, midY);
        })
        .onNodeClick((n: unknown) => {
          const node = n as { type?: string; id?: string };
          if (node.type === "paper" && node.id && node.id !== id) navigate(`/paper/${node.id}`);
        })
        .graphData({
          nodes: graphData.nodes.map((n) => ({ ...n })),
          links: graphData.links.map((l) => ({ ...l })),
        });

      graphInstanceRef.current = graph;
    });

    return () => {
      if (graphInstanceRef.current) {
        (graphInstanceRef.current as { _destructor?: () => void })?._destructor?.();
        graphInstanceRef.current = null;
      }
    };
  }, [graphData, graphLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  const [figuresExtractMsg, setFiguresExtractMsg] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [refetching, setRefetching] = useState(false);
  const [refetchError, setRefetchError] = useState<string | null>(null);
  // Inline meta editing
  const [metaEdit, setMetaEdit] = useState<Partial<{ title: string; year: string; doi: string; venue: string; abstract: string }>>({});

  const EXTRACT_STEPS = ["Loading model…", "Rendering pages…", "Detecting figures…", "Saving images…"];

  useEffect(() => {
    if (!figuresExtracting) { setFiguresExtractStep(0); return; }
    setFiguresExtractStep(0);
    const id = setInterval(() => {
      setFiguresExtractStep((s) => (s + 1) % EXTRACT_STEPS.length);
    }, 3500);
    return () => clearInterval(id);
  }, [figuresExtracting]);

  const handleExtractFigures = async () => {
    if (!id) return;
    setFiguresExtracting(true);
    setSelectedFigure(null);
    setFigureAnswer(null);
    setFiguresExtractMsg(null);
    try {
      const res = await extractFiguresForPaper(id, settings.figureCaptionMethod);
      const figs = await fetchFigures(id);
      setFigures(figs);
      setFiguresLoaded(true);
      setFiguresExtractMsg(`${res.extracted} figure${res.extracted !== 1 ? "s" : ""} extracted`);
    } catch (e) {
      setFiguresExtractMsg(e instanceof Error ? e.message : "Extraction failed");
    } finally {
      setFiguresExtracting(false);
    }
  };

  const handleFigureChat = async () => {
    if (!id || !selectedFigure || !figureQuestion.trim()) return;
    setFigureAnswering(true);
    setFigureAnswer(null);
    try {
      const res = await chatWithFigure(id, selectedFigure.id, figureQuestion.trim(), figureModel);
      setFigureAnswer(res.answer);
    } catch (e) {
      setFigureAnswer(`Error: ${e instanceof Error ? e.message : "Chat failed"}`);
    } finally {
      setFigureAnswering(false);
    }
  };

  const handleExtract = async () => {
    if (!id) return;
    setExtracting(true);
    try {
      const { references: found } = await extractReferences(id);
      setPendingRefs(found);
      setCheckedRefs(found.map(() => true));
    } catch {
      // ignore
    } finally {
      setExtracting(false);
    }
  };

  const handleSuggestTags = async () => {
    if (!id || !paper) return;
    setSuggestingTags(true);
    setTagSuggestOpen(true);
    try {
      const res = await suggestTags(paper.title, paper.abstract ?? undefined);
      setAllTagSuggestions(res.all_tags);
      setSuggestedExisting(res.existing);
      setSuggestedNew(res.new);
      const existing = tags.map((t) => t.name);
      setSelectedSugTags(new Set(res.existing.filter((t) => !existing.includes(t))));
    } finally {
      setSuggestingTags(false);
    }
  };

  const applyTagSuggestions = async () => {
    if (!id) return;
    const existing = tags.map((t) => t.name);
    const toApply = [...selectedSugTags].filter((t) => !existing.includes(t));
    const newOnes = toApply.filter((t) => !allTagSuggestions.includes(t));
    for (const name of newOnes) await createStandaloneTag(name);
    if (toApply.length) await applyTags(id, toApply);
    setTags(await apiFetch<Tag[]>(`/papers/${id}/tags`));
    setTagSuggestOpen(false);
    setSelectedSugTags(new Set());
  };

  const handleSuggestTopics = async () => {
    if (!id) return;
    setSuggestingTopics(true);
    setTopicSuggestOpen(true);
    try {
      const res = await suggestTopics(id);
      const existing = topics.map((t) => t.name);
      const fresh = res.topics.filter((t) => !existing.includes(t));
      setSuggestedTopics(res.topics);
      setSelectedSugTopics(new Set(fresh));
    } finally {
      setSuggestingTopics(false);
    }
  };

  const applyTopicSuggestions = async () => {
    if (!id) return;
    const existing = topics.map((t) => t.name);
    for (const name of selectedSugTopics) {
      if (!existing.includes(name)) {
        await apiFetch(`/papers/${id}/topics`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
      }
    }
    setTopics(await apiFetch<Topic[]>(`/papers/${id}/topics`));
    setTopicSuggestOpen(false);
    setSelectedSugTopics(new Set());
  };

  const handlePullReference = async (doi: string) => {
    setPullingDoi(doi);
    try {
      await ingestFromUrl(doi);
      // Reload references so the pulled ref gets its id + full metadata
      const { references: refs, cited_by } = await listReferences(id!);
      setReferences(refs);
      setCitedBy(cited_by);
    } catch {
      // ignore — stub stays in place
    } finally {
      setPullingDoi(null);
    }
  };

  const handleSaveRefs = async () => {
    if (!id || !pendingRefs) return;
    const selected = pendingRefs.filter((_, i) => checkedRefs[i]);
    if (selected.length > 0) {
      await saveReferences(id, selected).catch(() => {});
      const { references, cited_by } = await listReferences(id).catch(() => ({ references: [], cited_by: [] }));
      setReferences(references);
      setCitedBy(cited_by);
    }
    setPendingRefs(null);
  };

  const handleDeletePaper = async () => {
    if (!id) return;
    setDeleting(true);
    try {
      await deletePaper(id);
      navigate("/");
    } catch (e) {
      setDeleting(false);
      setConfirmDelete(false);
      alert(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const saveModalMetadata = async (next: { tags: string[]; topics: string[] }) => {
    if (!id) return { tags, topics };

    const currentTagNames = tags.map((tag) => tag.name);
    const currentTopicNames = topics.map((topic) => topic.name);

    const tagsToAdd = next.tags.filter((name) => !currentTagNames.includes(name));
    const tagsToRemove = currentTagNames.filter((name) => !next.tags.includes(name));
    const topicsToAdd = next.topics.filter((name) => !currentTopicNames.includes(name));
    const topicsToRemove = currentTopicNames.filter((name) => !next.topics.includes(name));

    await Promise.all([
      ...tagsToAdd.map((name) => apiFetch(`/papers/${id}/tags`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      })),
      ...tagsToRemove.map((name) => apiFetch(`/papers/${id}/tags/${encodeURIComponent(name)}`, { method: "DELETE" })),
      ...topicsToAdd.map((name) => apiFetch(`/papers/${id}/topics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      })),
      ...topicsToRemove.map((name) => apiFetch(`/papers/${id}/topics/${encodeURIComponent(name)}`, { method: "DELETE" })),
    ]);

    const [nextTags, nextTopics] = await Promise.all([
      apiFetch<Tag[]>(`/papers/${id}/tags`),
      apiFetch<Topic[]>(`/papers/${id}/topics`),
    ]);

    return { tags: nextTags, topics: nextTopics };
  };

  const addTag = async () => {
    if (!newTag.trim() || !id) return;
    await apiFetch(`/papers/${id}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newTag.trim() }),
    });
    setTags(await apiFetch<Tag[]>(`/papers/${id}/tags`));
    setNewTag("");
  };

  const addTopic = async () => {
    if (!newTopic.trim() || !id) return;
    await apiFetch(`/papers/${id}/topics`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newTopic.trim() }),
    });
    setTopics(await apiFetch<Topic[]>(`/papers/${id}/topics`));
    setNewTopic("");
  };

  const startDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const next = window.innerWidth - ev.clientX;
      setRightWidth(Math.min(700, Math.max(240, next)));
    };
    const onUp = () => {
      dragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  if (!paper) return <div className="p-8 text-sm text-gray-400">Loading…</div>;

  const BASE        = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
  const driveUrl    = paper.drive_file_id ? `https://drive.google.com/file/d/${paper.drive_file_id}/view` : null;
  const driveEmbed  = paper.drive_file_id ? `${BASE}/papers/${paper.id}/pdf` : null;

  const cycleStatus = async () => {
    if (!id) return;
    const cycle: Array<Paper["reading_status"]> = ["unread", "reading", "read"];
    const current = paper.reading_status ?? "unread";
    const next = cycle[(cycle.indexOf(current) + 1) % cycle.length];
    const updated = await apiFetch<typeof paper>(`/papers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reading_status: next }),
    });
    setPaper(updated);
  };

  const toggleBookmark = async () => {
    if (!id) return;
    const updated = await apiFetch<typeof paper>(`/papers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bookmarked: !paper.bookmarked }),
    });
    setPaper(updated);
  };

  const setRating = async (stars: number) => {
    if (!id) return;
    const newRating = paper.rating === stars ? null : stars;
    const updated = await apiFetch<typeof paper>(`/papers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating: newRating }),
    });
    setPaper(updated);
  };

  const downloadBibtex = async () => {
    const res = await fetch(`${BASE}/papers/${id}/bibtex`);
    if (!res.ok) return;
    const text = await res.text();
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${paper.title.slice(0, 40).replace(/[^\w\s]/g, "").trim()}.bib`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const STATUS_STYLES: Record<string, string> = {
    unread:  "bg-gray-100 text-gray-500",
    reading: "bg-blue-100 text-blue-600",
    read:    "bg-green-100 text-green-600",
  };
  const STATUS_LABELS: Record<string, string> = {
    unread: "📚 Unread",
    reading: "📖 Reading",
    read: "✅ Read",
  };
  const currentStatus = paper.reading_status ?? "unread";

  return (
    <div className="h-[calc(100vh-53px)] flex flex-col">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-white border-b border-gray-200 shrink-0 flex-wrap gap-2">
        <Link to="/" className="text-sm text-violet-600 hover:underline shrink-0">← Library</Link>
        <h1 className="text-sm font-medium text-gray-700 truncate max-w-md flex-1 text-center">{paper.title}</h1>

        {/* Paper controls */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Reading status */}
          <button
            onClick={cycleStatus}
            title="Click to cycle reading status"
            className={`text-xs px-2 py-1 rounded-full font-medium transition-colors ${STATUS_STYLES[currentStatus]}`}
          >
            {STATUS_LABELS[currentStatus]}
          </button>

          {/* Stars */}
          <div className="flex gap-0.5">
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                key={star}
                onClick={() => setRating(star)}
                title={`Rate ${star} star${star > 1 ? "s" : ""}`}
                className={`text-base leading-none transition-colors ${
                  star <= (paper.rating ?? 0) ? "text-amber-400" : "text-gray-200 hover:text-amber-300"
                }`}
              >
                ★
              </button>
            ))}
          </div>

          {/* Bookmark */}
          <button
            onClick={toggleBookmark}
            title={paper.bookmarked ? "Remove bookmark" : "Bookmark"}
            className={`text-lg leading-none transition-colors ${paper.bookmarked ? "text-amber-400" : "text-gray-300 hover:text-amber-300"}`}
          >
            ★
          </button>

          {/* BibTeX download */}
          <button
            onClick={downloadBibtex}
            title="Download BibTeX"
            className="text-xs text-gray-400 hover:text-violet-600 transition-colors px-2 py-1 border border-gray-200 rounded-lg"
          >
            .bib
          </button>

          <button
            onClick={() => setEditOpen(true)}
            className="text-xs text-gray-400 hover:text-violet-600 transition-colors"
          >
            Edit metadata
          </button>
        </div>
      </div>

      {/* Main two-column layout */}
      <div className="flex-1 flex overflow-hidden">

        {/* LEFT — abstract / PDF */}
        <div className="flex-1 flex flex-col overflow-hidden bg-gray-50">
          {/* Tab bar */}
          <div className="flex items-center gap-1 px-4 pt-3 pb-0 border-b border-gray-200 bg-white shrink-0">
            <button
              onClick={() => setLeftTab("abstract")}
              className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors -mb-px ${
                leftTab === "abstract"
                  ? "border-violet-600 text-violet-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              Abstract
            </button>
            {driveEmbed && (
              <button
                onClick={() => setLeftTab("pdf")}
                className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors -mb-px ${
                  leftTab === "pdf"
                    ? "border-violet-600 text-violet-600"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                PDF
              </button>
            )}
            <button
              onClick={() => setLeftTab("figures")}
              className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors -mb-px ${
                leftTab === "figures"
                  ? "border-violet-600 text-violet-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {figuresLoaded && figures.length > 0 ? `Figures (${figures.length})` : "Figures"}
            </button>
            {(paper.document_type === "book" || paper.document_type === "lecture_deck") && (
              <button
                onClick={() => setLeftTab("chapters")}
                className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors -mb-px ${
                  leftTab === "chapters"
                    ? "border-violet-600 text-violet-600"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                📚 Chapters
              </button>
            )}
            <button
              onClick={() => setLeftTab("graph")}
              className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors -mb-px ${
                leftTab === "graph"
                  ? "border-violet-600 text-violet-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              Graph
            </button>
            <button
              onClick={() => setLeftTab("people")}
              className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors -mb-px ${
                leftTab === "people"
                  ? "border-violet-600 text-violet-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              People
            </button>
            <button
              onClick={() => setLeftTab("meta")}
              className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors -mb-px ${
                leftTab === "meta"
                  ? "border-violet-600 text-violet-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              Metadata
            </button>
            {driveUrl && (
              <a
                href={driveUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto mb-1 flex items-center gap-1 text-xs text-gray-400 hover:text-violet-600 transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                </svg>
                Open in Drive
              </a>
            )}
          </div>

          {/* Abstract tab */}
          {leftTab === "abstract" && (
            <div className="flex-1 overflow-y-auto">
              <div className="max-w-2xl mx-auto px-8 py-10 space-y-6">
                <div>
                  <h2 className="text-xl font-semibold text-gray-900 leading-snug">{paper.title}</h2>
                  <div className="flex items-center gap-2 mt-1 flex-wrap">
                    {paper.year || paper.venue ? (
                      <p className="text-xs text-gray-400">
                        {paper.year}{paper.venue ? ` · ${paper.venue}` : ""}
                      </p>
                    ) : null}
                    {paper.document_type && paper.document_type !== "paper" && (
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${paper.document_type === "book" ? "bg-amber-100 text-amber-700" : "bg-blue-100 text-blue-700"}`}>
                        {paper.document_type === "book" ? "📚 Book" : "🎓 Lecture deck"}
                      </span>
                    )}
                  </div>
                  {authors.length > 0 && (
                    <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5">
                      {authors.map((a) => (
                        <span key={a.id} className="group flex items-center gap-1 text-sm text-gray-600">
                          <Link to={`/people?id=${a.id}`} className="hover:text-violet-600 transition-colors">
                            {a.name}
                          </Link>
                          {a.affiliation && (
                            <span className="text-xs text-gray-400">({a.affiliation})</span>
                          )}
                          <button
                            onClick={async () => {
                              if (!id) return;
                              await removeAuthor(id, a.id);
                              setAuthors((prev) => prev.filter((p) => p.id !== a.id));
                            }}
                            title="Remove from paper"
                            className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-400 transition-all text-xs leading-none"
                          >×</button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {paper.abstract && (
                  <div>
                    <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Abstract</p>
                    <p className="text-sm text-gray-700 leading-relaxed">{paper.abstract}</p>
                  </div>
                )}

                {paper.summary && (
                  <div className="bg-violet-50 border border-violet-100 rounded-xl p-5">
                    <p className="text-xs font-semibold text-violet-400 uppercase tracking-wide mb-2">AI Summary</p>
                    <div className="prose prose-sm max-w-none text-gray-700 prose-headings:text-gray-800 prose-a:text-violet-600">
                      <ReactMarkdown>{paper.summary}</ReactMarkdown>
                    </div>
                  </div>
                )}

                {paper.doi && (
                  <p className="text-xs text-gray-400">
                    DOI: <span className="font-mono">{paper.doi}</span>
                    {paper.citation_count != null && ` · ${paper.citation_count.toLocaleString()} citations`}
                  </p>
                )}

                {/* Delete */}
                <div className="pt-4 border-t border-gray-100">
                  {!confirmDelete ? (
                    <button
                      onClick={() => setConfirmDelete(true)}
                      className="text-xs text-gray-400 hover:text-red-500 transition-colors"
                    >
                      Delete this paper…
                    </button>
                  ) : (
                    <div className="flex items-center gap-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
                      <p className="text-xs text-red-700 flex-1">
                        This will permanently delete the paper, its PDF, all figures, and its note.
                        People, tags, and topics are kept.
                      </p>
                      <button
                        onClick={() => setConfirmDelete(false)}
                        disabled={deleting}
                        className="shrink-0 text-xs text-gray-500 hover:text-gray-700 disabled:opacity-50"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleDeletePaper}
                        disabled={deleting}
                        className="shrink-0 text-xs font-medium bg-red-600 text-white px-3 py-1.5 rounded-lg hover:bg-red-700 disabled:opacity-50"
                      >
                        {deleting ? "Deleting…" : "Delete"}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* PDF tab */}
          {leftTab === "pdf" && driveEmbed && (
            <iframe
              src={driveEmbed}
              className="flex-1 w-full border-0"
              allow="autoplay"
              title="PDF viewer"
            />
          )}

          {/* People tab */}
          {leftTab === "people" && (
            <div className="flex-1 overflow-y-auto">
              <div className="px-6 py-5 space-y-6">

                {/* Authors */}
                <div>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Authors</p>
                  {authors.length === 0 ? (
                    <p className="text-xs text-gray-400">No authors recorded.</p>
                  ) : (
                    <div className="space-y-2">
                      {authors.map((a) => (
                        <div key={a.id} className="flex items-center justify-between gap-3 rounded-xl border border-gray-100 bg-white px-4 py-3">
                          <div>
                            <Link to={`/people?id=${a.id}`} className="text-sm font-medium text-gray-800 hover:text-violet-600 transition-colors">
                              {a.name}
                            </Link>
                            {a.affiliation && (
                              <p className="text-xs text-gray-400 mt-0.5">{a.affiliation}</p>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-medium bg-violet-100 text-violet-600 px-2 py-0.5 rounded-full">author</span>
                            <button
                              onClick={async () => {
                                if (!id) return;
                                await removeAuthor(id, a.id);
                                setAuthors((prev) => prev.filter((p) => p.id !== a.id));
                              }}
                              title="Remove from paper"
                              className="text-gray-300 hover:text-red-400 transition-colors text-sm leading-none"
                            >×</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Involved people */}
                {involvesLoaded && involves.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Involved</p>
                    <div className="space-y-2">
                      {involves.map((p) => (
                        <div key={`${p.id}-${p.role}`} className="flex items-center justify-between gap-3 rounded-xl border border-gray-100 bg-white px-4 py-3">
                          <div>
                            <Link to={`/people?id=${p.id}`} className="text-sm font-medium text-gray-800 hover:text-violet-600 transition-colors">
                              {p.name}
                            </Link>
                            {p.affiliation && (
                              <p className="text-xs text-gray-400 mt-0.5">{p.affiliation}</p>
                            )}
                          </div>
                          <span className="text-[10px] font-medium bg-blue-100 text-blue-600 px-2 py-0.5 rounded-full">
                            {p.role}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {!involvesLoaded && <p className="text-xs text-gray-400">Loading…</p>}
              </div>
            </div>
          )}

          {/* Meta tab */}
          {leftTab === "meta" && (
            <div className="flex-1 overflow-y-auto">
              <div className="max-w-xl mx-auto px-6 py-5 space-y-6">

                {/* Editable fields */}
                <MetaSection title="Paper info">
                  <div className="space-y-2">
                    {(["title", "year", "venue", "doi", "abstract"] as const).map((field) => {
                      const currentVal = String(paper[field] ?? "");
                      const editVal = metaEdit[field] ?? currentVal;
                      const isDirty = editVal !== currentVal;
                      return (
                        <div key={field}>
                          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-0.5">{field}</p>
                          {field === "abstract" ? (
                            <textarea
                              value={editVal}
                              onChange={(e) => setMetaEdit((s) => ({ ...s, [field]: e.target.value }))}
                              onBlur={async () => {
                                if (!isDirty || !id) return;
                                const updated = await updatePaper(id, { [field]: editVal || null });
                                setPaper((p) => p ? { ...p, ...updated } : p);
                                setMetaEdit((s) => { const n = { ...s }; delete n[field]; return n; });
                              }}
                              rows={4}
                              className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-300 resize-none"
                            />
                          ) : (
                            <input
                              type="text"
                              value={editVal}
                              onChange={(e) => setMetaEdit((s) => ({ ...s, [field]: e.target.value }))}
                              onBlur={async () => {
                                if (!isDirty || !id) return;
                                const val = field === "year" ? (editVal ? Number(editVal) : null) : (editVal || null);
                                const updated = await updatePaper(id, { [field]: val });
                                setPaper((p) => p ? { ...p, ...updated } : p);
                                setMetaEdit((s) => { const n = { ...s }; delete n[field]; return n; });
                              }}
                              className={`w-full text-xs border rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-300 ${isDirty ? "border-violet-300 bg-violet-50" : "border-gray-200"}`}
                            />
                          )}
                        </div>
                      );
                    })}
                    {paper.citation_count != null && (
                      <div>
                        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-0.5">Citations</p>
                        <p className="text-xs text-gray-600">{paper.citation_count.toLocaleString()}</p>
                      </div>
                    )}
                    {paper.metadata_source && (
                      <div>
                        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-0.5">Metadata source</p>
                        <p className="text-xs text-gray-600">{paper.metadata_source}</p>
                      </div>
                    )}
                  </div>
                </MetaSection>

                {/* AI Summary */}
                {/* Re-fetch PDF — shown when paper has no PDF or missing authors/abstract */}
                {(paper.doi?.startsWith("arXiv:") || paper.doi?.startsWith("10.1101/")) && (
                  <MetaSection title="PDF & extraction">
                    <p className="text-xs text-gray-500 mb-2">
                      {paper.drive_file_id
                        ? "Re-download the PDF and re-run the full extraction pipeline (authors, abstract, summary, figures)."
                        : "No PDF uploaded yet. Download the PDF and run the full extraction pipeline."}
                    </p>
                    <button
                      onClick={async () => {
                        if (!id || refetching) return;
                        setRefetching(true);
                        setRefetchError(null);
                        try {
                          const res = await refetchPdf(id);
                          // Refresh paper + authors
                          const updated = await apiFetch<PaperFull>(`/papers/${id}`);
                          setPaper(updated);
                          const updatedAuthors = await apiFetch<Person[]>(`/papers/${id}/authors`);
                          setAuthors(updatedAuthors);
                        } catch (e) {
                          setRefetchError(e instanceof Error ? e.message : "Re-fetch failed");
                        } finally {
                          setRefetching(false);
                        }
                      }}
                      disabled={refetching}
                      className="text-xs px-3 py-1.5 bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 font-medium flex items-center gap-2"
                    >
                      {refetching && (
                        <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                        </svg>
                      )}
                      {refetching ? "Downloading & extracting…" : "↓ Download PDF & re-extract"}
                    </button>
                    {refetchError && <p className="text-xs text-red-500 mt-1">{refetchError}</p>}
                  </MetaSection>
                )}

                <MetaSection title="AI Summary">
                  <button
                    onClick={async () => {
                      if (!id || regenerating) return;
                      setRegenerating(true);
                      try {
                        const res = await regenerateSummary(id);
                        setPaper((p) => p ? { ...p, summary: res.summary } : p);
                      } catch (e) {
                        alert(e instanceof Error ? e.message : "Failed to regenerate summary");
                      } finally {
                        setRegenerating(false);
                      }
                    }}
                    disabled={regenerating}
                    className="text-xs px-3 py-1.5 bg-violet-50 text-violet-700 rounded-lg hover:bg-violet-100 disabled:opacity-50 font-medium"
                  >
                    {regenerating ? "Regenerating…" : "✦ Re-generate summary with AI"}
                  </button>
                  {!paper.summary && !regenerating && (
                    <p className="text-xs text-gray-400 mt-1">No summary yet.</p>
                  )}
                </MetaSection>

                {/* Topics */}
                <MetaSection title="Topics">
                  <div className="flex flex-wrap gap-1">
                    {topics.map((t) => (
                      <span key={t.id} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
                        {t.name}
                      </span>
                    ))}
                  </div>
                  <InlineAdd value={newTopic} onChange={setNewTopic} onAdd={addTopic} placeholder="Add topic…" />
                  <button
                    onClick={handleSuggestTopics}
                    disabled={suggestingTopics}
                    className="mt-1.5 w-full text-xs py-1 px-2 bg-blue-50 text-blue-600 rounded hover:bg-blue-100 disabled:opacity-50 flex items-center justify-center gap-1"
                  >
                    {suggestingTopics ? "Asking Claude…" : "✦ Suggest topics with AI"}
                  </button>
                  {topicSuggestOpen && !suggestingTopics && (
                    <div className="mt-2 border border-blue-200 rounded-lg overflow-hidden">
                      <div className="bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700 flex justify-between">
                        <span>Topic suggestions</span>
                        <button onClick={() => setTopicSuggestOpen(false)} className="text-blue-400 hover:text-blue-700">×</button>
                      </div>
                      <div className="p-3 space-y-2">
                        <div className="flex flex-wrap gap-1">
                          {suggestedTopics.map((t) => (
                            <button
                              key={t}
                              onClick={() => setSelectedSugTopics((p) => { const n = new Set(p); n.has(t) ? n.delete(t) : n.add(t); return n; })}
                              className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                                topics.map((x) => x.name).includes(t)
                                  ? "border-gray-200 text-gray-400 cursor-default"
                                  : selectedSugTopics.has(t)
                                  ? "bg-blue-600 text-white border-blue-600"
                                  : "border-dashed border-blue-400 text-blue-600 hover:bg-blue-50"
                              }`}
                            >
                              {topics.map((x) => x.name).includes(t) ? "✓ " : "+ "}{t}
                            </button>
                          ))}
                        </div>
                        <button
                          onClick={applyTopicSuggestions}
                          disabled={selectedSugTopics.size === 0}
                          className="w-full text-xs py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                        >
                          Apply {selectedSugTopics.size} topic{selectedSugTopics.size !== 1 ? "s" : ""}
                        </button>
                      </div>
                    </div>
                  )}
                </MetaSection>

                {/* Tags */}
                <MetaSection title="Tags">
                  <div className="flex flex-wrap gap-1">
                    {tags.map((t) => (
                      <span key={t.id} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                        {t.name}
                      </span>
                    ))}
                  </div>
                  <InlineAdd value={newTag} onChange={setNewTag} onAdd={addTag} placeholder="Add tag…" />
                  <button
                    onClick={handleSuggestTags}
                    disabled={suggestingTags}
                    className="mt-1.5 w-full text-xs py-1 px-2 bg-violet-50 text-violet-600 rounded hover:bg-violet-100 disabled:opacity-50 flex items-center justify-center gap-1"
                  >
                    {suggestingTags ? "Asking Claude…" : "✦ Suggest tags with AI"}
                  </button>
                  {tagSuggestOpen && !suggestingTags && (
                    <div className="mt-2 border border-violet-200 rounded-lg overflow-hidden">
                      <div className="bg-violet-50 px-3 py-2 text-xs font-semibold text-violet-700 flex justify-between">
                        <span>Tag suggestions</span>
                        <button onClick={() => setTagSuggestOpen(false)} className="text-violet-400 hover:text-violet-700">×</button>
                      </div>
                      <div className="p-3 space-y-2">
                        {suggestedNew.length > 0 && (
                          <div>
                            <p className="text-[10px] font-semibold text-gray-400 uppercase mb-1">New from AI</p>
                            <div className="flex flex-wrap gap-1">
                              {suggestedNew.map((t) => (
                                <button key={t} onClick={() => setSelectedSugTags((p) => { const n = new Set(p); n.has(t) ? n.delete(t) : n.add(t); return n; })}
                                  className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${selectedSugTags.has(t) ? "bg-violet-600 text-white border-violet-600" : "border-dashed border-violet-400 text-violet-600"}`}>
                                  + {t}
                                </button>
                              ))}
                            </div>
                          </div>
                        )}
                        <div>
                          <p className="text-[10px] font-semibold text-gray-400 uppercase mb-1">All tags</p>
                          <div className="flex flex-wrap gap-1 max-h-28 overflow-y-auto">
                            {allTagSuggestions.filter((t) => !tags.map((x) => x.name).includes(t)).map((t) => (
                              <button key={t} onClick={() => setSelectedSugTags((p) => { const n = new Set(p); n.has(t) ? n.delete(t) : n.add(t); return n; })}
                                className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${selectedSugTags.has(t) ? "bg-violet-600 text-white border-violet-600" : "border-gray-200 text-gray-600 hover:border-violet-400"}`}>
                                {t}
                              </button>
                            ))}
                          </div>
                        </div>
                        <div className="flex gap-1">
                          <input value={newTagDraft} onChange={(e) => setNewTagDraft(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter" && newTagDraft.trim()) { const clean = newTagDraft.toLowerCase().replace(/\s+/g, "-"); setSelectedSugTags((p) => new Set([...p, clean])); setSuggestedNew((p) => [...p, clean]); setNewTagDraft(""); } }}
                            placeholder="custom-tag" className="flex-1 text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none" />
                          <button onClick={() => { if (newTagDraft.trim()) { const clean = newTagDraft.toLowerCase().replace(/\s+/g, "-"); setSelectedSugTags((p) => new Set([...p, clean])); setSuggestedNew((p) => [...p, clean]); setNewTagDraft(""); } }}
                            className="text-xs px-2 py-1 bg-gray-100 rounded hover:bg-gray-200">+</button>
                        </div>
                        <button onClick={applyTagSuggestions} disabled={selectedSugTags.size === 0}
                          className="w-full text-xs py-1.5 bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50">
                          Apply {selectedSugTags.size} tag{selectedSugTags.size !== 1 ? "s" : ""}
                        </button>
                      </div>
                    </div>
                  )}
                </MetaSection>
              </div>
            </div>
          )}

          {/* Graph tab */}
          {leftTab === "graph" && (
            <div className="flex-1 overflow-hidden relative bg-gray-50">
              {!graphLoaded && (
                <div className="absolute inset-0 flex items-center justify-center text-xs text-gray-400 z-10">
                  Loading graph…
                </div>
              )}
              {graphLoaded && graphData && graphData.nodes.length === 0 && (
                <div className="absolute inset-0 flex items-center justify-center text-xs text-gray-400">
                  No connections yet.
                </div>
              )}
              <div ref={graphContainerRef} className="w-full h-full" />
            </div>
          )}

          {/* Figures tab */}
          {leftTab === "figures" && (
            <div className="flex-1 overflow-y-auto">
              <div className="px-6 py-5 space-y-5">

                {/* Toolbar */}
                <div className="flex items-center gap-3">
                  <button
                    onClick={handleExtractFigures}
                    disabled={figuresExtracting}
                    className="text-xs px-3 py-1.5 bg-violet-50 text-violet-700 rounded-lg hover:bg-violet-100 disabled:opacity-50 font-medium"
                  >
                    {figures.length > 0 ? "Re-extract" : "Extract figures"}
                  </button>
                  {figuresExtracting ? (
                    <span className="flex items-center gap-1.5 text-xs text-violet-500">
                      <span className="inline-block w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
                      {EXTRACT_STEPS[figuresExtractStep]}
                    </span>
                  ) : figuresExtractMsg ? (
                    <span className="text-xs text-gray-400">{figuresExtractMsg}</span>
                  ) : figures.length > 0 ? (
                    <span className="text-xs text-gray-400">{figures.length} figure{figures.length !== 1 ? "s" : ""}</span>
                  ) : null}
                </div>

                {/* Empty state */}
                {figuresLoaded && figures.length === 0 && (
                  <p className="text-sm text-gray-400 text-center py-12">
                    No figures extracted yet.<br />
                    <span className="text-xs">Click "Extract figures" to start.</span>
                  </p>
                )}

                {/* Figures — vertical stack */}
                {figures.length > 0 && (
                  <div className="space-y-6">
                    {figures.map((fig) => {
                      const isOpen = selectedFigure?.id === fig.id;
                      return (
                        <div key={fig.id} className="border border-gray-200 rounded-xl overflow-hidden">
                          {/* Image */}
                          {fig.drive_file_id ? (
                            <img
                              src={`${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/papers/${id}/figures/${fig.id}/image`}
                              alt={fig.caption ?? "Figure"}
                              className="w-3/4 mx-auto block object-contain bg-gray-50"
                              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                            />
                          ) : (
                            <div className="w-3/4 mx-auto h-40 bg-gray-100 flex items-center justify-center text-gray-400 text-xs">No preview</div>
                          )}

                          {/* Caption + ask button  also just 3/4*/}
                          <div className="px-4 py-3 bg-white border-t border-gray-100">
                            <div className="w-3/4 mx-auto flex items-start justify-between gap-3">
                              <div>
                                <p className="text-xs font-semibold text-gray-500">
                                  {fig.figure_number ? `Figure ${fig.figure_number}` : `Page ${fig.page_number}`}
                                </p>
                                {fig.caption && (
                                  <p className="text-sm text-gray-700 mt-0.5 leading-relaxed">{fig.caption}</p>
                                )}
                              </div>
                              <button
                                onClick={() => {
                                  setSelectedFigure(isOpen ? null : fig);
                                  setFigureAnswer(null);
                                  setFigureQuestion("");
                                }}
                                className="shrink-0 text-xs px-2.5 py-1 rounded-lg border border-gray-200 text-gray-500 hover:border-violet-300 hover:text-violet-600 transition-colors"
                              >
                                {isOpen ? "Close" : "Ask"}
                              </button>
                            </div>
                          </div>

                          {/* Inline chat — shown when expanded */}
                          {isOpen && (
                            <div className="px-4 py-4 space-y-3 border-t border-violet-100 bg-violet-50">
                              <div className="flex items-center justify-between">
                                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Ask about this figure</p>
                                <div className="flex rounded border border-gray-200 overflow-hidden text-xs">
                                  {(["claude", "claude-work"] as const).map((m) => (
                                    <button
                                      key={m}
                                      onClick={() => setFigureModel(m)}
                                      className={`px-2.5 py-1 ${figureModel === m ? "bg-violet-600 text-white" : "bg-white text-gray-500 hover:bg-gray-50"}`}
                                    >
                                      {m === "claude" ? "Claude" : "Work"}
                                    </button>
                                  ))}
                                </div>
                              </div>
                              <div className="flex gap-2">
                                <input
                                  type="text"
                                  value={figureQuestion}
                                  onChange={(e) => setFigureQuestion(e.target.value)}
                                  onKeyDown={(e) => e.key === "Enter" && handleFigureChat()}
                                  placeholder="What does this figure show?"
                                  disabled={figureAnswering}
                                  className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-violet-300 disabled:opacity-50"
                                />
                                <button
                                  onClick={handleFigureChat}
                                  disabled={figureAnswering || !figureQuestion.trim()}
                                  className="px-4 py-2 bg-violet-600 text-white text-sm rounded-lg hover:bg-violet-700 disabled:opacity-50"
                                >
                                  {figureAnswering ? "…" : "Ask"}
                                </button>
                              </div>
                              {figureAnswer && (
                                <div className="prose prose-sm max-w-none bg-white border border-gray-100 rounded-xl p-4">
                                  <ReactMarkdown>{figureAnswer}</ReactMarkdown>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Chapters tab (book/lecture deck only) */}
          {leftTab === "chapters" && id && (
            <div className="flex-1 overflow-y-auto">
              <div className="px-6 py-5">
                <BookChapters paperId={id} />
              </div>
            </div>
          )}
        </div>

        {/* Drag handle */}
        <div
          onMouseDown={startDrag}
          className="w-1 shrink-0 cursor-col-resize bg-gray-200 hover:bg-violet-400 transition-colors active:bg-violet-500"
        />

        {/* RIGHT — metadata + notes/chat */}
        <div className="shrink-0 flex flex-col bg-white overflow-hidden" style={{ width: rightWidth }}>

          {/* Tabs: Notes / Chat / References */}
          <div className="flex border-b border-gray-100 shrink-0">
            {(["notes", "chat", "references"] as RightTab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`flex-1 py-2 text-xs font-medium capitalize transition-colors
                  ${tab === t
                    ? "text-violet-600 border-b-2 border-violet-600"
                    : "text-gray-500 hover:text-gray-700"
                  }`}
              >
                {t}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-hidden p-3">
            {tab === "notes" && id && <NoteEditor paperId={id} />}
            {tab === "chat"  && id && <ChatPanel paperId={id} />}
            {tab === "references" && (
              <div className="h-full overflow-y-auto space-y-5 pb-4">

                {/* Extract button */}
                <button
                  onClick={handleExtract}
                  disabled={extracting}
                  className="w-full text-xs py-2 px-3 bg-violet-50 text-violet-700 rounded-lg hover:bg-violet-100 disabled:opacity-50 font-medium"
                >
                  {extracting ? "Extracting…" : "Extract references from PDF"}
                </button>

                {/* Pending refs */}
                {pendingRefs && (
                  <div className="border border-violet-200 rounded-xl overflow-hidden">
                    <div className="bg-violet-50 px-4 py-2.5 flex items-center justify-between">
                      <span className="text-xs font-semibold text-violet-700">
                        {pendingRefs.length} found — pick which to save
                      </span>
                      <button
                        onClick={() => setCheckedRefs(checkedRefs.every(Boolean) ? checkedRefs.map(() => false) : checkedRefs.map(() => true))}
                        className="text-[10px] text-violet-500 hover:text-violet-700 underline"
                      >
                        {checkedRefs.every(Boolean) ? "Deselect all" : "Select all"}
                      </button>
                    </div>

                    <div className="divide-y divide-gray-100">
                      {pendingRefs.map((ref, i) => (
                        <label key={i} className={`flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors ${checkedRefs[i] ? "bg-white" : "bg-gray-50"} hover:bg-violet-50`}>
                          <input
                            type="checkbox"
                            className="mt-0.5 shrink-0 accent-violet-600"
                            checked={checkedRefs[i] ?? true}
                            onChange={(e) => {
                              const next = [...checkedRefs];
                              next[i] = e.target.checked;
                              setCheckedRefs(next);
                            }}
                          />
                          <div className="min-w-0">
                            <p className={`text-xs leading-snug ${checkedRefs[i] ? "text-gray-800 font-medium" : "text-gray-400"}`}>
                              {ref.title}
                            </p>
                            {(ref.year || ref.doi) && (
                              <p className="text-[10px] text-gray-400 mt-0.5">
                                {[ref.year, ref.doi].filter(Boolean).join(" · ")}
                              </p>
                            )}
                          </div>
                        </label>
                      ))}
                    </div>

                    <div className="flex items-center gap-2 px-4 py-2.5 border-t border-gray-100 bg-gray-50">
                      <button onClick={() => setPendingRefs(null)} className="text-xs text-gray-400 hover:text-gray-600">
                        Discard
                      </button>
                      <button
                        onClick={handleSaveRefs}
                        disabled={checkedRefs.every((c) => !c)}
                        className="ml-auto text-xs bg-violet-600 text-white px-4 py-1.5 rounded-lg hover:bg-violet-700 disabled:opacity-40 font-medium"
                      >
                        Save {checkedRefs.filter(Boolean).length}
                      </button>
                    </div>
                  </div>
                )}

                {/* Saved references */}
                {references.length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-2">
                      Cites · {references.length}
                    </p>
                    <div className="space-y-1.5">
                      {references.map((ref, i) => {
                        const isPulled = !!(ref as any).metadata_source || !!(ref as any).abstract;
                        const doi = ref.doi;
                        const isStub = !isPulled && !!doi;
                        const isPulling = pullingDoi === doi;
                        return (
                          <div
                            key={i}
                            className={`rounded-lg border px-3 py-2.5 group transition-colors ${
                              isPulled || ref.id
                                ? "border-violet-100 bg-violet-50 hover:bg-violet-100 cursor-pointer"
                                : "border-gray-100 bg-white"
                            }`}
                            onClick={() => (isPulled || ref.id) && navigate(`/paper/${ref.id}`)}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-xs font-medium text-gray-800 leading-snug">{ref.title}</p>
                              {isPulled && (
                                <span className="shrink-0 text-[10px] text-green-600 font-semibold mt-0.5">✓ In library</span>
                              )}
                              {isStub && (
                                <button
                                  onClick={(e) => { e.stopPropagation(); handlePullReference(doi!); }}
                                  disabled={isPulling}
                                  className="shrink-0 text-[10px] font-medium bg-white border border-violet-200 text-violet-600 px-2 py-0.5 rounded-full hover:bg-violet-50 disabled:opacity-50"
                                >
                                  {isPulling ? "…" : "Pull ↓"}
                                </button>
                              )}
                            </div>
                            {(ref.year || doi) && (
                              <p className="text-[10px] text-gray-400 mt-1">
                                {[ref.year, doi?.replace("arXiv:", "arXiv: ")].filter(Boolean).join(" · ")}
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Cited by */}
                {citedBy.length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-2">
                      Cited by · {citedBy.length}
                    </p>
                    <div className="space-y-1.5">
                      {citedBy.map((ref, i) => (
                        <div
                          key={i}
                          className={`rounded-lg border px-3 py-2.5 transition-colors ${ref.id ? "border-violet-100 bg-violet-50 hover:bg-violet-100 cursor-pointer" : "border-gray-100 bg-white"}`}
                          onClick={() => ref.id && navigate(`/paper/${ref.id}`)}
                        >
                          <p className="text-xs font-medium text-gray-800 leading-snug">{ref.title}</p>
                          {ref.year && <p className="text-[10px] text-gray-400 mt-1">{ref.year}</p>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {references.length === 0 && citedBy.length === 0 && !pendingRefs && (
                  <p className="text-xs text-gray-400 text-center pt-6">No references saved yet.</p>
                )}
              </div>
            )}

          </div>
        </div>
      </div>

      {editOpen && (
        <EditPaperModal
          paper={paper}
          metadataEditor={{
            tags,
            topics,
            onSave: saveModalMetadata,
            onSaved: ({ tags: nextTags, topics: nextTopics }) => {
              setTags(nextTags);
              setTopics(nextTopics);
            },
          }}
          onSaved={(updated) => { setPaper((p) => p ? { ...p, ...updated } : p); setEditOpen(false); }}
          onClose={() => setEditOpen(false)}
        />
      )}
    </div>
  );
}

function MetaSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">{title}</p>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function InlineAdd({
  value, onChange, onAdd, placeholder,
}: {
  value: string; onChange: (v: string) => void; onAdd: () => void; placeholder: string;
}) {
  return (
    <div className="flex gap-1 mt-1">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onAdd()}
        placeholder={placeholder}
        className="flex-1 text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-violet-300"
      />
      <button onClick={onAdd} className="text-xs px-2 py-1 bg-gray-100 rounded hover:bg-gray-200">+</button>
    </div>
  );
}
