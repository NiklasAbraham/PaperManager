import { describe, expect, it } from "vitest";
import { niceScale } from "./BarChart";
import { formatCost, formatTokens, formatUptime, formatUsd, relativeTime } from "./format";

describe("format", () => {
  it("formats money by size", () => {
    expect(formatUsd(12.4)).toBe("$12.40");
    expect(formatUsd(1234.5)).toBe("$1,234.50");
    expect(formatUsd(0.0123)).toBe("$0.0123");
    expect(formatUsd(0.5)).toBe("$0.50");
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(null)).toBe("n/a");
  });

  it("says free for zero cost on LiteLLM and unknown without a price", () => {
    expect(formatCost(0, "litellm")).toBe("free");
    expect(formatCost(0, "anthropic")).toBe("$0.00");
    expect(formatCost(null, "anthropic", false)).toBe("unknown");
  });

  it("abbreviates tokens", () => {
    expect(formatTokens(950)).toBe("950");
    expect(formatTokens(12_345)).toBe("12.3k");
    expect(formatTokens(120_000)).toBe("120k");
    expect(formatTokens(1_500_000)).toBe("1.5M");
  });

  it("formats durations and relative times", () => {
    expect(formatUptime(93_784)).toBe("1 d 2 h");
    expect(formatUptime(3700)).toBe("1 h 1 min");
    expect(formatUptime(42)).toBe("42 s");
    const now = Date.parse("2026-11-12T10:00:00Z");
    expect(relativeTime("2026-11-12T09:55:00Z", now)).toBe("5 min ago");
    expect(relativeTime("2026-11-12T10:00:10Z", now)).toBe("just now");
    expect(relativeTime(null, now)).toBe("never");
  });

  it("rounds the chart axis up to a nice maximum", () => {
    expect(niceScale(0)).toEqual({ max: 1, step: 0.25 });
    expect(niceScale(0.42)).toEqual({ max: 0.6, step: 0.2 });
    expect(niceScale(12.4).max).toBeGreaterThanOrEqual(12.4);
  });
});
