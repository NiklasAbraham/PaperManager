/**
 * Single source of truth for the navigation. Desktop bar, dropdown menus and the mobile drawer
 * all render from NAV_ITEMS: adding a page to the navigation is one line here.
 */
export type NavGroup = "primary" | "explore" | "tools" | "account";

export interface NavItem {
  label: string;
  to: string;
  /** One line shown under the label in menus and the drawer. */
  description: string;
  group: NavGroup;
  adminOnly?: boolean;
  /** Match the exact path only (no sub-routes). */
  end?: boolean;
  /** Extra path prefixes that count as "inside" this item (e.g. "/paper" for Library). */
  also?: string[];
  /** Longer text for the Tools hub card; falls back to `description`. */
  detail?: string;
  /** Keep out of the Tools hub cards (the hub itself). */
  hub?: boolean;
}

export const GROUP_LABELS: Record<NavGroup, string> = {
  primary: "Main",
  explore: "Explore",
  tools: "Tools",
  account: "Account",
};

export const NAV_ITEMS: NavItem[] = [
  // Primary links in the bar
  { group: "primary", label: "Library", to: "/", end: true, also: ["/paper"], description: "All your papers" },
  { group: "primary", label: "Projects", to: "/projects", description: "Papers grouped by project, with concept maps" },
  { group: "primary", label: "People", to: "/people", description: "Authors and collaborators" },
  { group: "primary", label: "Chat", to: "/knowledge", description: "Ask questions across your library" },

  // Explore menu
  { group: "explore", label: "Graph", to: "/graph", description: "Papers, people and topics as a network; Cypher queries" },
  { group: "explore", label: "Topic map", to: "/topic-map", description: "Your library as a map of topics; projects as bubbles" },
  { group: "explore", label: "Find papers", to: "/literature", description: "Search arXiv, Semantic Scholar, PubMed, bioRxiv; keyword feed" },
  { group: "explore", label: "Conferences", to: "/conferences", description: "Browse conference proceedings" },
  { group: "explore", label: "Blogs", to: "/blogs", description: "Followed blogs and their posts" },
  { group: "explore", label: "Venues", to: "/venues", description: "Journals and conferences in your library" },
  { group: "explore", label: "Reports", to: "/reports", description: "Generated reports on your library" },
  { group: "explore", label: "Suggestions", to: "/suggestions", description: "Ideas for the app: vote and track status" },

  // Tools menu
  { group: "tools", label: "Bulk import", to: "/bulk-import", description: "Import a list of papers from JSON",
    detail: "Import a list of papers from a JSON file. Each entry can have a URL, arXiv ID, DOI, or title." },
  { group: "tools", label: "Merge duplicates", to: "/merge", description: "Find and merge near-duplicate papers",
    detail: "Scan all papers for near-duplicate titles, then merge them one by one, moving all connections to the paper you keep." },
  { group: "tools", label: "Image generation", to: "/tools/ideogram", description: "Ideogram on the on-demand GPU",
    detail: "Generate images with Ideogram 4 on the on-demand GPU. Compose with editable text/object boxes and refine one box at a time." },
  { group: "tools", label: "All tools", to: "/tools", end: true, hub: true, description: "Overview of every tool" },

  // Account menu
  { group: "account", label: "Settings", to: "/settings", description: "Models, prompts, export and import" },
  { group: "account", label: "Tokens", to: "/tokens", description: "Token usage and cost" },
  { group: "account", label: "Teammates", to: "/teammates", description: "Ask what a teammate has been thinking about" },
  { group: "account", label: "Admin", to: "/admin", adminOnly: true, description: "Users and system administration" },
  { group: "account", label: "Health", to: "/health", adminOnly: true, description: "Status of backend services" },
];

export function itemsFor(group: NavGroup, isAdmin: boolean): NavItem[] {
  return NAV_ITEMS.filter((i) => i.group === group && (isAdmin || !i.adminOnly));
}

function under(pathname: string, base: string): boolean {
  return pathname === base || pathname.startsWith(base + "/");
}

/** Whether the current route belongs to this item. */
export function isItemActive(item: NavItem, pathname: string): boolean {
  if (item.end) {
    if (pathname === item.to) return true;
  } else if (under(pathname, item.to)) {
    return true;
  }
  return (item.also ?? []).some((p) => under(pathname, p));
}

/** Whether the current route belongs to any (visible) item of the group, for menu buttons. */
export function isGroupActive(group: NavGroup, pathname: string, isAdmin: boolean): boolean {
  return itemsFor(group, isAdmin).some((i) => isItemActive(i, pathname));
}
