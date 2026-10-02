// Toggle chips that show or hide a project's papers by document type and by
// whether a PDF is stored.
import { PDF_KINDS, TYPE_KINDS, isVisible, pdfKind, typeKind, type KindedPaper } from "../lib/paperKinds";

interface Props {
  papers: KindedPaper[];
  hidden: Set<string>;
  onToggle: (key: string) => void;
  onReset: () => void;
}

export default function PaperKindFilter({ papers, hidden, onToggle, onReset }: Props) {
  const count = (fn: (p: KindedPaper) => string, key: string) => papers.filter((p) => fn(p) === key).length;
  const groups = [
    { name: "Type", kinds: TYPE_KINDS, fn: typeKind },
    { name: "PDF",  kinds: PDF_KINDS,  fn: pdfKind },
  ];
  const shown = papers.filter((p) => isVisible(p, hidden)).length;

  return (
    <div className="flex items-center gap-x-4 gap-y-2 flex-wrap mb-3" role="group" aria-label="Filter papers">
      {groups.map((g) => {
        const present = g.kinds.filter((k) => count(g.fn, k.key) > 0);
        if (present.length === 0) return null;
        return (
          <div key={g.name} className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">{g.name}</span>
            {present.map((k) => {
              const on = !hidden.has(k.key);
              return (
                <button
                  key={k.key}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onToggle(k.key)}
                  title={on ? `Hide ${k.label.toLowerCase()}` : `Show ${k.label.toLowerCase()}`}
                  className={`text-[11px] px-2 py-0.5 rounded-full border transition-colors ${
                    on
                      ? "bg-violet-50 border-violet-200 text-violet-700 hover:bg-violet-100"
                      : "bg-white border-gray-200 text-gray-400 line-through hover:text-gray-600"
                  }`}
                >
                  {k.label} <span className={on ? "text-violet-400" : "text-gray-300"}>{count(g.fn, k.key)}</span>
                </button>
              );
            })}
          </div>
        );
      })}
      {shown < papers.length && (
        <span className="text-[11px] text-gray-400">
          Showing {shown} of {papers.length} ·{" "}
          <button type="button" onClick={onReset} className="text-violet-600 hover:underline">Show all</button>
        </span>
      )}
    </div>
  );
}
