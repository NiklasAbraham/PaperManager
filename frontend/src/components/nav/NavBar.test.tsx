import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NavBar from "./NavBar";
import { CypherRedirect, ChatRedirect } from "./redirects";
import Discover from "../../pages/Discover";

const auth = { isAdmin: false, username: "alice", logout: vi.fn() };
const update = vi.fn();
const settings = { debugMode: false };

vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../../contexts/SettingsContext", () => ({
  useAppSettings: () => ({ settings, update }),
}));

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
}

function renderBar(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <NavBar />
      <Where />
    </MemoryRouter>
  );
}

beforeEach(() => {
  auth.isAdmin = false;
  settings.debugMode = false;
  vi.clearAllMocks();
});

describe("NavBar", () => {
  it("renders the primary links", () => {
    renderBar();
    for (const [name, href] of [
      ["Library", "/"],
      ["Projects", "/projects"],
      ["People", "/people"],
      ["Chat", "/knowledge"],
    ]) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    }
  });

  it("opens Explore and Tools with their items and descriptions", async () => {
    const user = userEvent.setup();
    renderBar();
    const explore = screen.getByRole("button", { name: /Explore/ });
    expect(explore).toHaveAttribute("aria-expanded", "false");
    await user.click(explore);
    expect(explore).toHaveAttribute("aria-expanded", "true");
    for (const n of ["Graph", "Find papers", "Conferences", "Blogs", "Venues", "Reports", "Suggestions"]) {
      expect(screen.getByRole("link", { name: new RegExp(`^${n}`) })).toBeInTheDocument();
    }
    expect(screen.getByText(/Papers, people and topics as a network/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Tools/ }));
    // opening another menu closes the first (outside click)
    expect(screen.queryByRole("link", { name: /^Graph/ })).not.toBeInTheDocument();
    for (const n of ["Bulk import", "Merge duplicates", "Image generation", "All tools"]) {
      expect(screen.getByRole("link", { name: new RegExp(`^${n}`) })).toBeInTheDocument();
    }
  });

  it("closes a menu on Escape and on navigation", async () => {
    const user = userEvent.setup();
    renderBar();
    await user.click(screen.getByRole("button", { name: /Explore/ }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("link", { name: /^Graph/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Explore/ }));
    await user.click(screen.getByRole("link", { name: /^Venues/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/venues");
    expect(screen.queryByRole("link", { name: /^Graph/ })).not.toBeInTheDocument();
  });

  it("hides admin-only items from non-admins and shows them to admins", async () => {
    const user = userEvent.setup();
    const { unmount } = renderBar();
    await user.click(screen.getByRole("button", { name: /alice/ }));
    expect(screen.getByRole("link", { name: /^Settings/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Tokens/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Teammates/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Admin/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Health/ })).not.toBeInTheDocument();
    unmount();

    auth.isAdmin = true;
    renderBar();
    await user.click(screen.getByRole("button", { name: /alice/ }));
    expect(screen.getByRole("link", { name: /^Admin/ })).toHaveAttribute("href", "/admin");
    expect(screen.getByRole("link", { name: /^Health/ })).toHaveAttribute("href", "/health");
  });

  it("marks a menu button active when the route is inside it", () => {
    renderBar("/conferences");
    expect(screen.getByRole("button", { name: /Explore/ }).className).toContain("bg-accent-lo");
    expect(screen.getByRole("button", { name: /Tools/ }).className).not.toContain("bg-accent-lo");
    expect(screen.getByRole("link", { name: "Library" }).className).not.toContain("bg-accent-lo");
  });

  it("keeps Library active on a paper page and Tools active on /tools/ideogram", () => {
    renderBar("/paper/abc");
    expect(screen.getByRole("link", { name: "Library" }).className).toContain("bg-accent-lo");
  });

  it("toggles debug mode from the account menu and shows the DEBUG badge", async () => {
    const user = userEvent.setup();
    const { unmount } = renderBar();
    expect(screen.queryByText("DEBUG")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /alice/ }));
    await user.click(screen.getByRole("switch", { name: /Debug mode/ }));
    expect(update).toHaveBeenCalledWith({ debugMode: true });
    unmount();
    settings.debugMode = true;
    renderBar();
    expect(screen.getAllByText("DEBUG").length).toBeGreaterThan(0);
  });

  it("logs out only after confirmation", async () => {
    const user = userEvent.setup();
    renderBar();
    await user.click(screen.getByRole("button", { name: /alice/ }));
    vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    await user.click(screen.getByRole("button", { name: "Logout" }));
    expect(auth.logout).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /alice/ }));
    vi.spyOn(window, "confirm").mockReturnValueOnce(true);
    await user.click(screen.getByRole("button", { name: "Logout" }));
    expect(auth.logout).toHaveBeenCalledTimes(1);
  });

  it("mobile drawer lists every group and closes on navigation", async () => {
    const user = userEvent.setup();
    auth.isAdmin = true;
    renderBar();
    await user.click(screen.getByRole("button", { name: "Open menu" }));
    const drawer = screen.getByRole("dialog", { name: "Navigation" });
    for (const h of ["Main", "Explore", "Tools", "Account"]) {
      expect(within(drawer).getByRole("heading", { name: h })).toBeInTheDocument();
    }
    for (const n of ["Library", "Projects", "People", "Chat", "Graph", "Find papers", "Bulk import", "All tools", "Settings", "Admin", "Health"]) {
      expect(within(drawer).getByRole("link", { name: new RegExp(`^${n}`) })).toBeInTheDocument();
    }
    await user.click(within(drawer).getByRole("link", { name: /^Blogs/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/blogs");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("mobile drawer hides admin items from non-admins", async () => {
    const user = userEvent.setup();
    renderBar();
    await user.click(screen.getByRole("button", { name: "Open menu" }));
    const drawer = screen.getByRole("dialog");
    expect(within(drawer).queryByRole("link", { name: /^Admin/ })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("redirects", () => {
  function renderRoutes(path: string) {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/cypher" element={<CypherRedirect />} />
          <Route path="/chat" element={<ChatRedirect />} />
          <Route path="/discover" element={<Discover />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    );
  }

  it("/cypher?q=X goes to /graph?view=query&q=X", () => {
    renderRoutes("/cypher?q=X");
    expect(screen.getByTestId("where")).toHaveTextContent("/graph?view=query&q=X");
  });

  it("/cypher without a query goes to /graph?view=query", () => {
    renderRoutes("/cypher");
    expect(screen.getByTestId("where")).toHaveTextContent("/graph?view=query");
  });

  it("/cypher keeps an encoded query intact", () => {
    renderRoutes("/cypher?q=MATCH%20(n)%20RETURN%20n");
    const p = new URLSearchParams(screen.getByTestId("where").textContent!.split("?")[1]);
    expect(p.get("view")).toBe("query");
    expect(p.get("q")).toBe("MATCH (n) RETURN n");
  });

  it("/discover goes to /literature?tab=search", () => {
    renderRoutes("/discover");
    expect(screen.getByTestId("where")).toHaveTextContent("/literature?tab=search");
  });

  it("/chat goes to /knowledge", () => {
    renderRoutes("/chat");
    expect(screen.getByTestId("where")).toHaveTextContent("/knowledge");
  });
});
