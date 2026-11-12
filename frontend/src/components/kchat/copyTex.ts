// Ported from the thesis desk's src/copyTex.ts; keep the two in sync. replaceMath is exported for tests.
/**
 * Copying rendered maths gives its LaTeX source.
 *
 * KaTeX renders every formula twice, as visible HTML and as hidden MathML, so a plain
 * browser copy flattens both into one glyph per line. KaTeX's MathML keeps the source in
 * <annotation encoding="application/x-tex">; this handler swaps each formula in the copied
 * selection for that source, `$...$` inline and `$$` on its own lines for display maths,
 * which is what the chat and remark-math read back. Same idea as katex/contrib/copy-tex,
 * but display maths keeps its own lines and paragraphs keep their line breaks, so pasting
 * prose with formulas into the composer round-trips. A selection that starts or ends inside
 * a formula takes in the whole formula. The text/html flavour stays the selected HTML.
 * One document-level listener covers the chat, previews and concept cards.
 */

const TEX = 'annotation[encoding="application/x-tex"]';

function closestMath(node: Node): Element | null {
  const el = node instanceof Element ? node : node.parentElement;
  return el?.closest('.katex-display') ?? el?.closest('.katex') ?? null;
}

/** The LaTeX source of a rendered formula, or null if KaTeX left no annotation. */
function sourceOf(el: Element): string | null {
  if (el.classList.contains('katex-error')) return el.textContent;
  const ann = el.querySelector(TEX);
  return ann ? ann.textContent : null;
}

/** A node that renders its text verbatim, so innerText keeps the line breaks of the source. */
function verbatim(text: string, block: boolean): HTMLElement {
  const el = document.createElement(block ? 'div' : 'span');
  el.style.whiteSpace = 'pre-wrap';
  el.textContent = text;
  return el;
}

/** Replaces every formula in `root` by its delimited source; false if one had no source. */
export function replaceMath(root: ParentNode): boolean {
  let ok = true;
  for (const el of Array.from(root.querySelectorAll('.katex-display'))) {
    const tex = sourceOf(el);
    if (tex === null) { ok = false; continue; }
    el.replaceWith(verbatim(`$$\n${tex.trim()}\n$$`, true));
  }
  for (const el of Array.from(root.querySelectorAll('.katex, .katex-error'))) {
    const tex = sourceOf(el);
    if (tex === null) { ok = false; continue; }
    el.replaceWith(verbatim(`$${tex.trim()}$`, false));
  }
  return ok;
}

/**
 * The plain text of the selection with formulas as LaTeX. Laid out off-screen so innerText
 * applies the browser's own block rules (paragraphs, list items, table rows), as a normal
 * copy would.
 */
function plainText(fragment: DocumentFragment): string {
  const host = document.createElement('div');
  host.setAttribute('aria-hidden', 'true');
  host.style.cssText = 'position:fixed;left:-100000px;top:0;width:800px;white-space:normal;';
  host.appendChild(fragment);
  document.body.appendChild(host);
  try {
    return host.innerText.replace(/\n{3,}/g, '\n\n').trim();
  } finally {
    host.remove();
  }
}

function onCopy(event: ClipboardEvent) {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount || !event.clipboardData) return;

  const texts: string[] = [];
  const htmls: string[] = [];
  let hasMath = false;
  for (let i = 0; i < selection.rangeCount; i++) {
    // A copy of the range, so the visible selection is left as the user made it.
    const range = selection.getRangeAt(i).cloneRange();
    const start = closestMath(range.startContainer);
    if (start) range.setStartBefore(start);
    const end = closestMath(range.endContainer);
    if (end) range.setEndAfter(end);

    const html = range.cloneContents();
    if (html.querySelector('.katex, .katex-error')) hasMath = true;
    const wrap = document.createElement('div');
    wrap.appendChild(html.cloneNode(true));
    htmls.push(wrap.innerHTML);

    if (!replaceMath(html)) return; // no source to copy: leave it to the browser
    texts.push(plainText(html));
  }
  if (!hasMath) return;

  event.clipboardData.setData('text/plain', texts.join('\n'));
  event.clipboardData.setData('text/html', htmls.join(''));
  event.preventDefault();
}

let installed = false;
export function installCopyTex() {
  if (installed) return;
  installed = true;
  document.addEventListener('copy', onCopy);
}
