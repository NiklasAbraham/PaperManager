import { useState } from "react";
import { formatUsd } from "./format";

export interface Bar {
  key: string;
  /** Short x-axis label, shown for a few evenly spaced bars. */
  label: string;
  value: number;
  /** Tooltip / readout text: "12 Nov: 14 calls, 120k tokens, $0.42". */
  title: string;
}

const W = 720;
const H = 220;
const M = { top: 10, right: 8, bottom: 26, left: 56 };

/** Round the axis maximum up to 1, 2, 2.5, 5 or 10 times a power of ten, and pick the tick step. */
export function niceScale(max: number, target = 4): { max: number; step: number } {
  if (!(max > 0)) return { max: 1, step: 0.25 };
  const rough = max / target;
  const pow = Math.pow(10, Math.floor(Math.log10(rough)));
  const f = rough / pow;
  const mult = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  const step = mult * pow;
  return { max: Number((Math.ceil(max / step - 1e-9) * step).toFixed(10)), step };
}

/**
 * A small SVG bar chart in one accent hue. Zero values draw as a hairline on the baseline (a gap, not
 * a missing day). Every bar is focusable and carries a <title> tooltip; the same text appears in a
 * live readout under the chart, so hover, focus and screen readers all get the numbers.
 */
export default function BarChart({
  bars,
  ariaLabel,
  formatTick = (v: number) => (v === 0 ? "$0" : formatUsd(v)),
}: {
  bars: Bar[];
  ariaLabel: string;
  formatTick?: (v: number) => string;
}) {
  const [active, setActive] = useState<string | null>(null);
  const maxVal = bars.reduce((m, b) => Math.max(m, b.value), 0);
  const { max, step } = niceScale(maxVal);
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const slot = bars.length ? plotW / bars.length : plotW;
  const barW = Math.max(2, Math.min(28, slot * 0.7));
  const y = (v: number) => M.top + plotH - (v / max) * plotH;
  const ticks: number[] = [];
  for (let v = 0; v <= max + step / 1000; v += step) ticks.push(Number(v.toFixed(10)));
  const labelEvery = Math.max(1, Math.ceil(bars.length / 7));
  const activeBar = bars.find((b) => b.key === active);

  return (
    <div>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="group"
          aria-label={ariaLabel}
          className="h-auto w-full min-w-[520px]"
          onMouseLeave={() => setActive(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className="stroke-line" strokeWidth={t === 0 ? 1 : 0.5} />
              <text x={M.left - 6} y={y(t) + 3.5} textAnchor="end" className="fill-ink-3" fontSize={10}>
                {formatTick(t)}
              </text>
            </g>
          ))}
          {bars.map((b, i) => {
            const cx = M.left + slot * i + slot / 2;
            const h = b.value > 0 ? Math.max(1.5, (b.value / max) * plotH) : 0;
            const on = active === b.key;
            return (
              <g
                key={b.key}
                tabIndex={0}
                role="img"
                aria-label={b.title}
                data-testid="bar"
                onMouseEnter={() => setActive(b.key)}
                onFocus={() => setActive(b.key)}
                onBlur={() => setActive(null)}
                className="outline-none [&:focus-visible>rect.hit]:fill-accent-lo"
              >
                <title>{b.title}</title>
                <rect className="hit fill-transparent" x={cx - slot / 2} y={M.top} width={slot} height={plotH} />
                {b.value > 0 ? (
                  <rect
                    x={cx - barW / 2}
                    y={M.top + plotH - h}
                    width={barW}
                    height={h}
                    rx={Math.min(2, barW / 3)}
                    className={on ? "fill-accent" : "fill-accent opacity-80"}
                  />
                ) : (
                  <rect x={cx - barW / 2} y={M.top + plotH - 1.5} width={barW} height={1.5} className="fill-ink-3 opacity-60" />
                )}
                {i % labelEvery === 0 ? (
                  <text x={cx} y={H - 8} textAnchor="middle" className="fill-ink-3" fontSize={10}>
                    {b.label}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>
      <p aria-live="polite" className="mt-1 min-h-[1.25rem] text-xs text-ink-2">
        {activeBar ? activeBar.title : <span className="text-ink-3">Hover or focus a bar for the numbers.</span>}
      </p>
    </div>
  );
}
