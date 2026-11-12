import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import { Link } from "react-router-dom";
import { mdPlugins } from "../../lib/markdown";

const components: Components = {
  a({ href, children, node: _node, ...rest }) {
    void _node;
    if (href && href.startsWith("/paper/")) {
      return <Link to={href}>{children}</Link>;
    }
    return (
      <a {...rest} href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
};

/** The body of a report: GFM and KaTeX, library links as router links, other links in a new tab. */
export default function ReportMarkdown({ markdown }: { markdown: string }) {
  return (
    <div className="prose max-w-[70ch] text-ink prose-headings:text-ink prose-a:text-accent prose-a:no-underline hover:prose-a:underline">
      <ReactMarkdown {...mdPlugins} components={components}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
