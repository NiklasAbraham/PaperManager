import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { describe, expect, it } from "vitest";
import { differingParts, rehypeFigureStrips, type HNode } from "./figureStrips";

const ID = "c7d9ec3d-0df1-4c18-970f-7f6dc34e5e3e";
const img = (n: number) => `![fig ${n}](/papers/${ID}/figures/f${n}/image)`;

/** The block structure after the plugin: "strip(3)" for a strip of 3 images, "p(1)" for a paragraph of images, "p" otherwise. */
function shape(md: string): string[] {
  const proc = unified().use(remarkParse).use(remarkRehype).use(rehypeFigureStrips);
  const tree = proc.runSync(proc.parse(md)) as HNode;
  return (tree.children ?? [])
    .filter((n) => n.type === "element")
    .map((n) => {
      const imgs = (n.children ?? []).filter((c) => c.tagName === "img").length;
      if (n.tagName === "div") return `strip(${imgs})`;
      return imgs ? `p(${imgs})` : "p";
    });
}

describe("rehypeFigureStrips", () => {
  it("leaves one and two images as they are", () => {
    expect(shape(img(1))).toEqual(["p(1)"]);
    expect(shape(`${img(1)}\n${img(2)}`)).toEqual(["p(2)"]);
    expect(shape(`${img(1)}\n\n${img(2)}`)).toEqual(["p(1)", "p(1)"]);
  });

  it("makes three consecutive lines of one paragraph a strip", () => {
    expect(shape(`${img(1)}\n${img(2)}\n${img(3)}`)).toEqual(["strip(3)"]);
  });

  it("makes three paragraphs separated by blank lines a strip", () => {
    expect(shape(`${img(1)}\n\n${img(2)}\n\n\n${img(3)}\n\n${img(4)}`)).toEqual(["strip(4)"]);
  });

  it("counts images across a mixed paragraph and a following paragraph", () => {
    expect(shape(`${img(1)}\n${img(2)}\n\n${img(3)}`)).toEqual(["strip(3)"]);
  });

  it("does not join images that have text between them", () => {
    expect(shape(`${img(1)}\n\n${img(2)}\n\nA sentence.\n\n${img(3)}`)).toEqual(["p(1)", "p(1)", "p", "p(1)"]);
    expect(shape(`${img(1)} and ${img(2)} and ${img(3)}`)).toEqual(["p(3)"]);
  });

  it("keeps surrounding text and other blocks in order", () => {
    expect(shape(`Intro.\n\n${img(1)}\n${img(2)}\n${img(3)}\n\nAfter.`)).toEqual(["p", "strip(3)", "p"]);
  });

  it("treats an all-figures glob as its own strip, even alone", () => {
    expect(shape(`![All figures](/papers/${ID}/figures/*)`)).toEqual(["strip(1)"]);
    expect(shape(`${img(1)}\n\n![All](/papers/${ID}/figures/*)\n\n${img(2)}`)).toEqual(["p(1)", "strip(1)", "p(1)"]);
  });

  it("never throws on a hast tree with surprises", () => {
    const weird = { type: "root", children: [{ type: "element", tagName: "p" }, { type: "text" }, { type: "element", tagName: "p", children: [{ type: "element", tagName: "img" }] }] } as HNode;
    expect(() => rehypeFigureStrips()(weird)).not.toThrow();
  });

  it("copes with half-written image markdown while streaming", () => {
    for (const md of [`${img(1)}\n${img(2)}\n![fig 3](/papers/${ID}/fig`, `${img(1)}\n![fi`, "![", `${img(1)}\n\n${img(2)}\n\n![x](`]) {
      expect(() => shape(md)).not.toThrow();
    }
  });
});

describe("differingParts", () => {
  it("strips the common prefix and suffix on word boundaries", () => {
    expect(differingParts(["Figure 2: loss curve", "Figure 3: accuracy curve"])).toEqual(["2: loss", "3: accuracy"]);
    expect(differingParts(["Fig. 1 of the paper", "Fig. 2 of the paper"])).toEqual(["1", "2"]);
  });

  it("does not cut inside words", () => {
    expect(differingParts(["Figure 1a", "Figure 1b"])).toEqual(["1a", "1b"]);
  });

  it("falls back to 1, 2, ... when nothing remains", () => {
    expect(differingParts(["same", "same", "same"])).toEqual(["1", "2", "3"]);
    expect(differingParts(["", "", ""])).toEqual(["1", "2", "3"]);
    expect(differingParts(["Loss", "Loss curve"])).toEqual(["1", "2"]);
    expect(differingParts(["only"])).toEqual(["1"]);
    expect(differingParts([])).toEqual([]);
  });

  it("keeps strings that share nothing whole", () => {
    expect(differingParts(["alpha", "beta"])).toEqual(["alpha", "beta"]);
  });
});
