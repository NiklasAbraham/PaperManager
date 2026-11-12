import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Conversation } from "../../types";
import { parseConcept } from "./ConceptBlock";
import { mentionText, parseMentions } from "./Composer";
import { filterConversations } from "./ConversationList";
import { ChatLinksContext, imageUrl, Markdown, normaliseMath } from "./Markdown";
import { normalise, parseSource, plddtColour, resiSet } from "./structure/viewer";

describe("parseConcept (```concept blocks)", () => {
  it("accepts a bare formula spec and fills missing fields", () => {
    const c = parseConcept('{"type": "formula", "main_latex": "a^2+b^2=c^2"}');
    expect(c?.spec).toMatchObject({ type: "formula", title: "", caption: "", steps: [] });
  });

  it("unwraps a concept file and stringifies object data_json", () => {
    const c = parseConcept(JSON.stringify({ label: "Loss", spec: { type: "graph", chart_type: "points", data_json: { points: [[0, 1]] } } }));
    expect(c?.label).toBe("Loss");
    expect(c?.spec.type === "graph" && JSON.parse(c.spec.data_json)).toEqual({ points: [[0, 1]] });
  });

  it("returns null while streaming or for unknown types", () => {
    expect(parseConcept('{"type": "formula", "main_')).toBeNull();
    expect(parseConcept('{"type": "3d", "code": "x"}')).toBeNull();
    expect(parseConcept('{"type": "2d-anim"}')).toBeNull();
  });
});

describe("parseSource (```structure blocks)", () => {
  it("reads a bare PDB id and an AlphaFold id", () => {
    expect(parseSource("6vxx")).toEqual({ spec: { models: [{ pdb: "6VXX" }] } });
    expect(parseSource("AF-P69905-F1")).toEqual({ spec: { models: [{ afdb: "P69905", color: "plddt" }] } });
  });

  it("reads a JSON spec and a flat one-model spec", () => {
    expect(parseSource('{"models": [{"pdb": "1UBQ"}], "title": "Ubiquitin"}')).toMatchObject({ spec: { title: "Ubiquitin" } });
    expect(normalise({ pdb: "1UBQ", caption: "c" })).toMatchObject({ caption: "c", models: [{ pdb: "1UBQ" }] });
  });

  it("returns null for half a spec or anything else", () => {
    expect(parseSource('{"models": [')).toBeNull();
    expect(parseSource("hello world")).toBeNull();
  });

  it("parses residue ranges and pLDDT bands", () => {
    const r = resiSet("10,12-14")!;
    expect([9, 10, 11, 12, 14, 15].map(r)).toEqual([false, true, false, true, true, false]);
    expect(plddtColour(95)).not.toBe(plddtColour(40));
  });
});

describe("composer mentions", () => {
  it("parses quoted and bare mentions", () => {
    expect(parseMentions('@project:"Protein design" and @tag:nlp').map((m) => [m.type, m.value]))
      .toEqual([["project", "Protein design"], ["tag", "nlp"]]);
  });
  it("quotes values that need it", () => {
    expect(mentionText("topic", "Drug Discovery")).toBe('@topic:"Drug Discovery"');
    expect(mentionText("tag", "nlp")).toBe("@tag:nlp");
  });
});

describe("filterConversations", () => {
  const conv = (id: string, title: string, parent_id?: string, branch_label?: string): Conversation => ({
    id, title, parent_id, branch_label, created_at: "", updated_at: "", compacted: false, message_count: 2,
  });
  it("keeps the parent of a matching fork", () => {
    const list = [conv("a", "Diffusion"), conv("b", "Diffusion", "a", "What about AlphaFold?"), conv("c", "Other")];
    expect(filterConversations(list, "alphafold").map((c) => c.id)).toEqual(["a", "b"]);
  });
});

describe("chat markdown", () => {
  it("normalises \\( \\) and \\[ \\] maths", () => {
    expect(normaliseMath("a \\(x\\) b")).toBe("a $x$ b");
    expect(normaliseMath("\\[y\\]")).toContain("$$\ny\n$$");
  });

  it("only lets library figure paths and https images through", () => {
    expect(imageUrl("/papers/c7d9ec3d-0df1-4c18-970f-7f6dc34e5e3e/figures/f1/image")).toMatch(/\/papers\/.+\/image$/);
    expect(imageUrl("https://example.org/x.png")).toBe("https://example.org/x.png");
    expect(imageUrl("/etc/passwd")).toBeNull();
    expect(imageUrl("javascript:alert(1)")).toBeNull();
  });

  it("renders paper links as citations and concept blocks as cards", () => {
    const id = "c7d9ec3d-0df1-4c18-970f-7f6dc34e5e3e";
    const text = `See [RFdiffusion](/paper/${id}).\n\n\`\`\`concept\n{"type": "formula", "title": "Pythagoras", "main_latex": "a^2+b^2=c^2"}\n\`\`\``;
    const { container } = render(
      <ChatLinksContext.Provider value={{ openPaper: () => {}, openFigure: () => {} }}>
        <Markdown text={text} />
      </ChatLinksContext.Provider>,
    );
    expect(container.querySelector("a.kc-cite")?.getAttribute("href")).toBe(`/paper/${id}`);
    expect(container.querySelector(".kc-concept-formula .kc-card-title")?.textContent).toBe("Pythagoras");
  });
});
