import { Link } from "react-router-dom";

interface Tool {
  to: string;
  name: string;
  description: string;
  emoji: string;
  available: boolean;
}

// Grid of tools. Add new entries here as more tools land.
const TOOLS: Tool[] = [
  {
    to: "/tools/ideogram",
    name: "Ideogram Chat",
    description:
      "Generate images with Ideogram 4 on the on-demand GPU. Compose with editable text/object boxes and refine one box at a time.",
    emoji: "🎨",
    available: true,
  },
];

function ToolCard({ tool }: { tool: Tool }) {
  const inner = (
    <div
      className={`h-full rounded-xl border p-5 transition-all ${
        tool.available
          ? "border-gray-200 bg-white hover:border-violet-300 hover:shadow-md cursor-pointer"
          : "border-dashed border-gray-200 bg-gray-50 opacity-70"
      }`}
    >
      <div className="text-3xl mb-3">{tool.emoji}</div>
      <div className="font-semibold text-gray-900">{tool.name}</div>
      <div className="mt-1 text-sm text-gray-500 leading-snug">{tool.description}</div>
      {!tool.available && (
        <div className="mt-3 inline-block text-[10px] font-semibold uppercase tracking-wide text-gray-400">
          Coming soon
        </div>
      )}
    </div>
  );
  return tool.available ? (
    <Link to={tool.to} className="block h-full">
      {inner}
    </Link>
  ) : (
    <div className="h-full">{inner}</div>
  );
}

export default function Tools() {
  return (
    <div className="max-w-6xl mx-auto p-8">
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Tools</h1>
      <p className="text-sm text-gray-500 mb-6">Utilities that run alongside your library.</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {TOOLS.map((t) => (
          <ToolCard key={t.to} tool={t} />
        ))}
      </div>
    </div>
  );
}
