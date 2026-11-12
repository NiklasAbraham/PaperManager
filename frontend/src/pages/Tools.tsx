import { Link } from "react-router-dom";
import { NAV_ITEMS } from "../components/nav/navConfig";

// The cards come from the Tools menu entries (navConfig.ts): add a tool there and it shows here.
const TOOLS = NAV_ITEMS.filter((i) => i.group === "tools" && !i.hub);

export default function Tools() {
  return (
    <div className="max-w-6xl mx-auto p-4 sm:p-8">
      <h1 className="text-2xl font-bold text-ink mb-1">Tools</h1>
      <p className="text-sm text-ink-2 mb-6">Utilities that run alongside your library.</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {TOOLS.map((t) => (
          <Link
            key={t.to}
            to={t.to}
            className="block h-full rounded-xl border border-line bg-raised p-5 transition-all hover:border-accent-border hover:shadow-md"
          >
            <div className="text-sm font-semibold text-ink">{t.label}</div>
            <div className="mt-1 text-sm text-ink-2 leading-snug">{t.detail ?? t.description}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
