import katex from "katex";
import { describe, expect, it } from "vitest";
import { installCopyTex, replaceMath } from "./copyTex";

const frag = (html: string) => {
  const d = document.createElement("div");
  d.innerHTML = html;
  return d;
};
const render = (tex: string, displayMode = false) => katex.renderToString(tex, { output: "htmlAndMathml", displayMode });

describe("copyTex", () => {
  it("replaces inline maths by its $...$ source", () => {
    const root = frag(`<p>Energy ${render("x^2")} here</p>`);
    expect(replaceMath(root)).toBe(true);
    expect(root.textContent).toBe("Energy $x^2$ here");
  });

  it("replaces display maths by $$ on its own lines", () => {
    const root = frag(render("\\frac{a}{b}", true));
    expect(replaceMath(root)).toBe(true);
    expect(root.textContent).toBe("$$\n\\frac{a}{b}\n$$");
  });

  it("reports a formula without an annotation and leaves it", () => {
    const root = frag('<span class="katex"><span class="katex-html">x</span></span>');
    expect(replaceMath(root)).toBe(false);
    expect(root.querySelector(".katex")).not.toBeNull();
  });

  it("installs once", () => {
    expect(() => { installCopyTex(); installCopyTex(); }).not.toThrow();
  });
});
