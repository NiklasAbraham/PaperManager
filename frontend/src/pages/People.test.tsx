import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import People from "./People";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, apiFetch: vi.fn() };
});

// A library holds thousands of people; the list must draw a window of them, not one row each.
const PEOPLE = Array.from({ length: 3000 }, (_, i) => ({
  id: `p${i}`,
  name: `Given${i} Family${i}`,
  affiliation: i % 2 ? "Odd University" : "Even Institute",
  paper_count: 1,
}));

describe("People list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.apiFetch).mockImplementation(async (url: string) => (String(url).startsWith("/people") ? PEOPLE : []) as never);
  });

  it("renders a window of the list and grows it on request", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><People /></MemoryRouter>);

    await screen.findByText("Given0 Family0");
    const personButtons = () => screen.getAllByRole("listitem").filter((li) => /Given\d+ Family\d+/.test(li.textContent ?? ""));
    expect(personButtons().length).toBe(200);

    await user.click(screen.getByRole("button", { name: /Show 200 more/ }));
    await waitFor(() => expect(personButtons().length).toBe(400));
  });

  it("search filters the whole list, not only the drawn window", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><People /></MemoryRouter>);
    await screen.findByText("Given0 Family0");

    await user.type(screen.getByPlaceholderText("Search people…"), "Family2999");
    await waitFor(() => expect(screen.getByText("Given2999 Family2999")).toBeInTheDocument());
    expect(screen.queryByText("Given0 Family0")).not.toBeInTheDocument();
  });
});
