import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NavBar from "./NavBar";
import { loadFeatures, resetFeatures } from "../../lib/features";

const auth = { isAdmin: false, isAuthenticated: true, username: "alice", logout: vi.fn() };
vi.mock("../../contexts/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../../contexts/SettingsContext", () => ({
  useAppSettings: () => ({ settings: { debugMode: false }, update: vi.fn() }),
}));

function answerStatus(body: unknown, ok = true) {
  const fetchMock = vi.fn().mockResolvedValue({ ok, json: async () => body });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function openExplore() {
  const user = userEvent.setup();
  render(<MemoryRouter><NavBar /></MemoryRouter>);
  await user.click(screen.getByRole("button", { name: /Explore/ }));
}

describe("the optional Paper feed entry in the navigation", () => {
  beforeEach(() => {
    resetFeatures();
    auth.isAuthenticated = true;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("is hidden when the instance has the feed switched off", async () => {
    const fetchMock = answerStatus({ enabled: false });
    await openExplore();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/feed\/status$/);
    expect(screen.queryByRole("link", { name: /Paper feed/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Suggestions/ })).toBeInTheDocument();     // the rest is untouched
  });

  it("is hidden when the status cannot be read", async () => {
    answerStatus({}, false);
    await openExplore();
    expect(screen.queryByRole("link", { name: /Paper feed/ })).not.toBeInTheDocument();
  });

  it("appears under Explore when the feed is enabled", async () => {
    answerStatus({ enabled: true });
    await openExplore();
    expect(await screen.findByRole("link", { name: /Paper feed/ })).toHaveAttribute("href", "/feed");
  });

  it("asks nothing before login", async () => {
    auth.isAuthenticated = false;
    const fetchMock = answerStatus({ enabled: true });
    await openExplore();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: /Paper feed/ })).not.toBeInTheDocument();
  });

  it("loadFeatures asks only once after a success", async () => {
    const fetchMock = answerStatus({ enabled: true });
    await loadFeatures();
    await loadFeatures();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
