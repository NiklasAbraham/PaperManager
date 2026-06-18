import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import Projects from "./Projects";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    listProjects: vi.fn(),
  };
});

describe("Projects", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listProjects).mockResolvedValue([]);
  });

  it("keeps create-project form open when '+ New' is clicked again", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <Projects />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(client.listProjects).toHaveBeenCalled();
    });

    const newButton = screen.getByRole("button", { name: /\+ New/i });
    await user.click(newButton);
    await user.click(newButton);

    expect(screen.getByPlaceholderText("Project name…")).toBeInTheDocument();
  });
});
