// New in PaperManager (the desk documents figure strips but has not built them); the same rule is in the chat's system prompt.
/**
 * Figure strips: a rehype plugin and two helpers.
 *
 * Three or more images "in a row" render as one thumbnail strip instead of full-width figures.
 * "In a row" means images that are the only content of consecutive paragraphs or lines: consecutive
 * lines of one paragraph, or paragraphs separated only by blank lines, whitespace and <br>. One or
 * two images stay figures. An image whose URL is `/papers/<uuid>/figures/*` is a strip of ALL the
 * extracted figures of that paper (its alt text is the strip's title), whatever surrounds it.
 *
 * The plugin only rewrites the hast tree (runs become `<div class="kc-strip-src">` holding the img
 * nodes); Markdown.tsx renders that div as <FigureStrip>. It never throws: on any surprise the tree
 * is left as it was, so half-written streaming markdown shows as before.
 */

export const STRIP_CLASS = "kc-strip-src";
/** Images a run needs before it becomes a strip. */
export const STRIP_MIN = 3;

/** `/papers/<uuid>/figures/*`: every figure of one paper. The capture is the paper id. */
export const FIGURE_GLOB = /^\/papers\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/figures\/\*$/i;

export type HNode = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HNode[];
};

const isImg = (n: HNode) => n.type === "element" && n.tagName === "img";
const isBr = (n: HNode) => (n.type === "element" && n.tagName === "br") || (n.type === "raw" && /^<br\s*\/?>$/i.test((n.value ?? "").trim()));
const isBlank = (n: HNode) => (n.type === "text" && !(n.value ?? "").trim()) || isBr(n) || n.type === "comment";
const srcOf = (n: HNode) => String(n.properties?.src ?? "");
const isGlob = (n: HNode) => FIGURE_GLOB.test(srcOf(n));

/** The images of a paragraph that holds nothing else (whitespace and <br> aside); null for any other node. */
function imageOnly(n: HNode): HNode[] | null {
  if (isImg(n)) return [n];
  if (n.type !== "element" || n.tagName !== "p") return null;
  const imgs: HNode[] = [];
  for (const c of n.children ?? []) {
    if (isImg(c)) imgs.push(c);
    else if (!isBlank(c)) return null;
  }
  return imgs.length ? imgs : null;
}

const strip = (imgs: HNode[]): HNode => ({
  type: "element", tagName: "div", properties: { className: [STRIP_CLASS] }, children: imgs,
});
const para = (imgs: HNode[]): HNode => ({ type: "element", tagName: "p", properties: {}, children: imgs });

/** One run of image-only nodes becomes strips (3+ plain images, each glob on its own) and leftover paragraphs. */
function rewriteRun(imgs: HNode[]): HNode[] {
  const out: HNode[] = [];
  let group: HNode[] = [];
  const flush = () => {
    if (group.length >= STRIP_MIN) out.push(strip(group));
    else if (group.length) out.push(para(group));
    group = [];
  };
  for (const img of imgs) {
    if (isGlob(img)) { flush(); out.push(strip([img])); } else group.push(img);
  }
  flush();
  return out;
}

function rewrite(parent: HNode): void {
  const kids = parent.children;
  if (!kids) return;
  const next: HNode[] = [];
  let i = 0;
  while (i < kids.length) {
    const first = imageOnly(kids[i]);
    if (!first) {
      rewrite(kids[i]);
      next.push(kids[i]);
      i++;
      continue;
    }
    // Extend the run over image-only nodes separated by blank nodes only.
    const nodes = [kids[i]];
    const imgs = [...first];
    let j = i + 1;
    for (;;) {
      let k = j;
      while (k < kids.length && isBlank(kids[k])) k++;
      const more = k < kids.length ? imageOnly(kids[k]) : null;
      if (!more) break;
      nodes.push(kids[k]);
      imgs.push(...more);
      j = k + 1;
    }
    if (imgs.length >= STRIP_MIN || imgs.some(isGlob)) next.push(...rewriteRun(imgs));
    else next.push(...nodes.flatMap((n, idx) => (idx ? [{ type: "text", value: "\n" }, n] : [n])));
    i = j;
  }
  parent.children = next;
}

/** rehype plugin: collect runs of images into strip placeholders. */
export function rehypeFigureStrips() {
  return (tree: HNode) => {
    try {
      // Work on a copy of the child lists so a failure half way leaves the original tree untouched.
      const copy = structuredCloneTree(tree);
      rewrite(copy);
      tree.children = copy.children;
    } catch {
      /* leave the tree as it was */
    }
  };
}

function structuredCloneTree(n: HNode): HNode {
  return { ...n, children: n.children?.map(structuredCloneTree) };
}

/* -------------------------------------------------------------- labels */

const SEPARATORS = /^[\s:;,.|–—-]+|[\s:;,.|–—-]+$/g;

/**
 * The part of each string that differs: the longest common prefix and suffix are cut on word
 * boundaries ("Figure 2: loss" / "Figure 3: accuracy" give "2: loss" / "3: accuracy").
 * When nothing remains for some string (equal strings, empty alt texts) the labels are "1", "2", ...
 */
export function differingParts(strings: string[]): string[] {
  const numbered = strings.map((_, i) => String(i + 1));
  if (strings.length < 2) return numbered;
  const words = strings.map((s) => s.trim().split(/\s+/).filter(Boolean));
  const minLen = Math.min(...words.map((w) => w.length));
  let pre = 0;
  while (pre < minLen && words.every((w) => w[pre] === words[0][pre])) pre++;
  let suf = 0;
  while (suf < minLen - pre && words.every((w) => w[w.length - 1 - suf] === words[0][words[0].length - 1 - suf])) suf++;
  const parts = words.map((w) => w.slice(pre, w.length - suf).join(" ").replace(SEPARATORS, ""));
  return parts.some((p) => !p) ? numbered : parts;
}
