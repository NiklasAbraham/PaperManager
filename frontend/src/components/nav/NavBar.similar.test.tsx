import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NavBar from "./NavBar";
import { itemsFor } from "./navConfig";
import { resetFeatures } from "../../lib/features";

const auth = { isAdmin: false, isAuthenticated: true, username: "alice", logout: vi.fn() };
vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../../contexts/SettingsContext", () => ({
  useAppSettings: () => ({ settings: { debugMode: false }, update: vi.fn() }),
}));

async function openExplore(feedBody: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => feedBody });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<MemoryRouter><NavBar /></MemoryRouter>);
  await user.click(screen.getByRole("button", { name: /Explore/ }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
}

describe("the Similar papers entry in the navigation", () => {
  beforeEach(() => resetFeatures());
  afterEach(() => vi.unstubAllGlobals());

  it("is in the Explore menu on an instance without the feed", async () => {
    await openExplore({ enabled: false });
    expect(screen.getByRole("link", { name: /Similar papers/ })).toHaveAttribute("href", "/similar");
    expect(screen.queryByRole("link", { name: /Paper feed/ })).not.toBeInTheDocument();
  });

  it("is next to the Paper feed entry when the feed is on", async () => {
    await openExplore({ enabled: true });
    expect(await screen.findByRole("link", { name: /Paper feed/ })).toHaveAttribute("href", "/feed");
    expect(screen.getByRole("link", { name: /Similar papers/ })).toHaveAttribute("href", "/similar");
  });

  it("is not gated by a feature", () => {
    const item = itemsFor("explore", false).find((i) => i.to === "/similar");
    expect(item).toBeDefined();
    expect(item?.feature).toBeUndefined();
  });
});
