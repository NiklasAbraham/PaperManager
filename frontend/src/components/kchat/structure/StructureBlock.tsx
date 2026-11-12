// Ported from the thesis desk's StructureBlock (keep in sync), without the repository-file sources.
import { useMemo } from 'react';
import { StructureView } from './StructureView';
import { parseSource } from './viewer';

/**
 * A ```structure fenced block in an answer: a PDB id, `AF-<UniProt>`, or a spec as
 * JSON (see types.ts). While the block is still streaming it shows a placeholder; JSON that
 * is complete but not a usable spec shows what is wrong with it.
 */
export default function StructureBlock({ source }: { source: string }) {
  // Re-parsed only when the block's own text changes, not on every streamed token around it.
  const parsed = useMemo(() => parseSource(source), [source]);
  if (!parsed) return <div className="kc-card kc-card-pending">structure …</div>;
  if ('error' in parsed) return <div className="kc-card kc-card-pending">structure spec not usable — {parsed.error}</div>;
  return <StructureView spec={parsed.spec} />;
}
