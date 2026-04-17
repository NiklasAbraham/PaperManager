import { useNavigate } from "react-router-dom";
import type { Paper } from "../types";

const SOURCE_COLORS: Record<string, string> = {
  semantic_scholar: "bg-green-100 text-green-700",
  crossref: "bg-green-100 text-green-700",
  llm: "bg-yellow-100 text-yellow-700",
  heuristic: "bg-red-100 text-red-700",
};

export default function PaperCard({ paper }: { paper: Paper }) {
  const navigate = useNavigate();
  const summaryPreview = paper.summary?.split("\n").slice(0, 2).join(" ") ?? "";

  return (
    <div
      onClick={() => navigate(`/paper/${paper.id}`)}
      className="bg-white border border-gray-200 rounded-lg p-4 cursor-pointer hover:shadow-md hover:border-violet-300 transition-all"
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <h3 className="font-medium text-gray-900 text-sm leading-snug line-clamp-2">
          {paper.title}
        </h3>
        {paper.year && (
          <span className="text-xs text-gray-400 shrink-0">{paper.year}</span>
        )}
      </div>

      {summaryPreview && (
        <p className="text-xs text-gray-500 line-clamp-2 mt-1">{summaryPreview}</p>
      )}

      <div className="mt-3 flex flex-wrap gap-1">
        {paper.metadata_source && (
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${SOURCE_COLORS[paper.metadata_source] ?? "bg-gray-100 text-gray-500"}`}>
            {paper.metadata_source}
          </span>
        )}
        {paper.citation_count != null && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600">
            {paper.citation_count.toLocaleString()} citations
          </span>
        )}
      </div>
    </div>
  );
}
