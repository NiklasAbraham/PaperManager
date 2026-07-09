import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach } from "vitest";
import * as client from "../api/client";
import IdeogramChat from "./IdeogramChat";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    startIdeogramSession: vi.fn().mockResolvedValue({ status: "ready", job_id: "ig1" }),
    getIdeogramStatus: vi.fn().mockResolvedValue({ status: "ready", job_id: "ig1" }),
    stopIdeogramSession: vi.fn().mockResolvedValue({ stopped: true }),
    ideogramMagicPrompt: vi.fn(),
    ideogramGenerate: vi.fn(),
  };
});

describe("IdeogramChat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (client.startIdeogramSession as ReturnType<typeof vi.fn>).mockResolvedValue({ status: "ready", job_id: "ig1" });
    (client.getIdeogramStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ status: "ready", job_id: "ig1" });
  });

  it("starts a GPU session on mount and reaches ready", async () => {
    render(<IdeogramChat />);
    expect(client.startIdeogramSession).toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText("GPU ready")).toBeInTheDocument());
  });

  it("regenerates a single edited box with the locked seed", async () => {
    (client.ideogramGenerate as ReturnType<typeof vi.fn>).mockResolvedValue({
      image_base64: "Zm9v", // "foo"
      seed: 42,
      caption: null,
    });

    render(<IdeogramChat />);
    await waitFor(() => expect(screen.getByText("GPU ready")).toBeInTheDocument());

    // The tool starts blank ("from zero") — load the example boxes first.
    await userEvent.click(screen.getByRole("button", { name: /template/i }));

    // Edit the first (text) box from the template.
    const textInput = screen.getByDisplayValue("HELLO");
    await userEvent.clear(textInput);
    await userEvent.type(textInput, "WORLD");

    // Click the per-box "Regenerate box" (locked seed).
    const regenButtons = screen.getAllByRole("button", { name: /regenerate box/i });
    await userEvent.click(regenButtons[0]);

    await waitFor(() => expect(client.ideogramGenerate).toHaveBeenCalled());
    const body = (client.ideogramGenerate as ReturnType<typeof vi.fn>).mock.calls[0][0];
    // The edited text is included, and the seed is the locked default (42).
    expect(body.caption_json.compositional_deconstruction.elements[0].text).toBe("WORLD");
    expect(body.seed).toBe(42);

    // The returned image renders.
    await waitFor(() => {
      const img = screen.getByAltText("generated") as HTMLImageElement;
      expect(img.src).toContain("data:image/png;base64,Zm9v");
    });
  });

  it("uses a fresh random seed for 'Regenerate all'", async () => {
    (client.ideogramGenerate as ReturnType<typeof vi.fn>).mockResolvedValue({
      image_base64: "YmFy",
      seed: 999,
      caption: null,
    });
    render(<IdeogramChat />);
    await waitFor(() => expect(screen.getByText("GPU ready")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /regenerate all/i }));

    await waitFor(() => expect(client.ideogramGenerate).toHaveBeenCalled());
    const body = (client.ideogramGenerate as ReturnType<typeof vi.fn>).mock.calls[0][0];
    // Fresh seed differs from the locked default (42).
    expect(body.seed).not.toBe(42);
  });
});

  it("opens the history drawer", async () => {
    render(<IdeogramChat />);
    await waitFor(() => expect(screen.getByText("GPU ready")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /^history$/i }));
    // IndexedDB is unavailable in jsdom → history is empty, drawer still renders.
    await waitFor(() => expect(screen.getByText(/no saved generations/i)).toBeInTheDocument());
  });

  it("disables Export PNG until an image exists", async () => {
    render(<IdeogramChat />);
    await waitFor(() => expect(screen.getByText("GPU ready")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /export png/i })).toBeDisabled();
  });
