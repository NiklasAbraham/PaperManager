import type { SimilarHit } from "../../api/similar";

/** What "Use this paper as the query" puts into the text box: the title, a blank line, the abstract. */
export function queryFromHit(hit: SimilarHit): string {
  return [hit.title, hit.abstract || hit.snippet].filter(Boolean).join("\n\n");
}
