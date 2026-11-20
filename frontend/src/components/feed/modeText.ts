import type { FeedMode } from "../../api/feed";

/** One line on how the list is ranked right now. */
export function modeText(mode: FeedMode | null | undefined, positives: number | null | undefined): string {
  const n = positives ?? 0;
  if (mode === "classifier") return `Ranked by a model trained on ${n} papers from your library`;
  if (mode === "similarity") return `Ranked by similarity to ${n} paper${n === 1 ? "" : "s"} from your library (a model needs 10)`;
  if (mode === "newest") return "Newest first: rate or save papers to get a personal ranking";
  return "";
}
