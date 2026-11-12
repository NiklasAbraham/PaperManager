// Ported from the thesis desk's Markdown renderer (KaTeX, GFM, highlighted code,
// ```concept and ```structure cards), with library links instead of repository paths.
// Works with or without a ChatLinksContext: without one, images open in a new tab and
// paper citations are plain links to /paper/<id>.
import { createContext, lazy, memo, Suspense, useContext, useState } from "react";
import { Link, useInRouterContext } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import "katex/dist/katex.min.css";
import { apiUrl } from "../../api/client";
import ConceptBlock from "./ConceptBlock";
import { installCopyTex } from "./copyTex";
import { FigureStrip, PaperFigureStrip } from "./FigureStrip";
import { FIGURE_GLOB, rehypeFigureStrips, STRIP_CLASS, type HNode } from "./figureStrips";
import { PAPER_LINK } from "./sections";

// Copying rendered maths gives its LaTeX source; one document-level listener, installed once.
if (typeof document !== "undefined") installCopyTex();

// 3Dmol and the viewer code load only when an answer holds a structure.
const StructureBlock = lazy(() => import("./structure/StructureBlock"));

/**
 * Models often write display maths as \[ ... \] and inline as \( ... \);
 * remark-math only understands $ delimiters, so normalise first.
 */
export function normaliseMath(src: string): string {
  return src
    .replace(/\\\[([\s\S]*?)\\\]/g, (_m, body) => `\n$$\n${body}\n$$\n`)
    .replace(/\\\((.+?)\\\)/g, (_m, body) => `$${body}$`);
}

type HastNode = HNode;
const hastText = (n: HastNode): string => n.value ?? (n.children ?? []).map(hastText).join("");

/** The source of a fenced block in `lang` (```concept, ```structure), or null for any other <pre>. */
function fencedSource(pre: HastNode | undefined, lang: string): string | null {
  const code = pre?.children?.find((c) => c.tagName === "code");
  const cls = code?.properties?.className;
  return code && Array.isArray(cls) && cls.includes(`language-${lang}`) ? hastText(code) : null;
}

/** Figure images of library papers are backend paths; anything else must be an absolute https URL. */
export function imageUrl(src: string): string | null {
  if (/^\/papers\/[0-9a-f-]{36}\/figures\/[\w-]+\/image$/i.test(src)) return apiUrl(src);
  if (/^https:\/\//i.test(src)) return src;
  return null;
}

/** What the chat page does when a citation or a figure in an answer is clicked. */
export type ChatLinks = {
  openPaper: (id: string, title: string) => void;
  openFigure: (src: string, caption: string) => void;
};
export const ChatLinksContext = createContext<ChatLinks | null>(null);

function MdImage({ src, alt }: { src: string; alt: string }) {
  const links = useContext(ChatLinksContext);
  const url = imageUrl(src);
  const [broken, setBroken] = useState(false);
  if (!url || broken) {
    return (
      <span className="kc-figure kc-figure-broken" title={src}>
        <span className="kc-figure-broken-label">figure not shown</span>
        <code>{src}</code>
      </span>
    );
  }
  const inner = (
    <>
      <img src={url} alt={alt} loading="lazy" onError={() => setBroken(true)} />
      {alt && <span className="kc-figure-caption">{alt}</span>}
    </>
  );
  // No chat page around (no preview pane): the image opens in a new tab.
  if (!links) {
    return <a className="kc-figure" href={url} target="_blank" rel="noreferrer" title="Open the figure in a new tab">{inner}</a>;
  }
  return (
    <button type="button" className="kc-figure" title="Open the figure beside the chat"
      onClick={() => links.openFigure(url, alt)}>
      {inner}
    </button>
  );
}

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  const links = useContext(ChatLinksContext);
  const inRouter = useInRouterContext();
  return (
    <div className="kc-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[
          rehypeFigureStrips as never,
          // output htmlAndMathml: the MathML annotation is what copyTex.ts copies.
          [rehypeKatex, { strict: false, throwOnError: false, output: "htmlAndMathml" }],
          // rehype-highlight 7 has no ignoreMissing option: unknown languages are already left unhighlighted.
          [rehypeHighlight, { detect: false }],
        ]}
        components={{
          pre({ node, children, ...rest }) {
            const concept = fencedSource(node as HastNode | undefined, "concept");
            if (concept !== null) return <ConceptBlock source={concept} />;
            const structure = fencedSource(node as HastNode | undefined, "structure");
            if (structure !== null) {
              return (
                <Suspense fallback={<div className="kc-card kc-card-pending">structure …</div>}>
                  <StructureBlock source={structure} />
                </Suspense>
              );
            }
            return <pre {...rest}>{children}</pre>;
          },
          div({ node, className, children, ...rest }) {
            const cls = typeof className === "string" ? className : "";
            if (!cls.split(" ").includes(STRIP_CLASS)) return <div className={className} {...rest}>{children}</div>;
            const imgs = ((node as HastNode | undefined)?.children ?? []).filter((c) => c.tagName === "img");
            const items = imgs.map((c) => ({ src: String(c.properties?.src ?? ""), alt: String(c.properties?.alt ?? "") }));
            const glob = items.length === 1 ? FIGURE_GLOB.exec(items[0].src) : null;
            if (glob) return <PaperFigureStrip paperId={glob[1]} title={items[0].alt || undefined} toUrl={imageUrl} onOpenBeside={links?.openFigure} />;
            return <FigureStrip items={items.map((x) => ({ ...x, url: imageUrl(x.src) }))} onOpenBeside={links?.openFigure} />;
          },
          img({ src, alt }) {
            return <MdImage src={String(src ?? "")} alt={alt ?? ""} />;
          },
          a({ node: _n, href, children, ...rest }) {
            const target = href ?? "";
            const paper = PAPER_LINK.exec(target);
            if (paper && !links) {
              // No preview pane: an app route, opened in the same tab.
              return inRouter
                ? <Link to={`/paper/${paper[1]}`} className="kc-cite">{children}</Link>
                : <a href={`/paper/${paper[1]}`} className="kc-cite">{children}</a>;
            }
            if (paper && links) {
              const title = hastText((_n ?? { type: "root" }) as HastNode);
              return (
                <a href={target} className="kc-cite" title="Open this paper beside the chat"
                  onClick={(e) => { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); links.openPaper(paper[1], title); }}>
                  {children}
                </a>
              );
            }
            return <a href={target} target="_blank" rel="noreferrer" {...rest}>{children}</a>;
          },
        }}
      >
        {normaliseMath(text)}
      </ReactMarkdown>
    </div>
  );
});
