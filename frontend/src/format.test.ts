import { describe, expect, it } from "vitest";

import {
  formatCount,
  formatDuration,
  formatMs,
  formatRelative,
  niceTicks,
  percentile,
} from "./format";

describe("formatMs", () => {
  it.each([
    [null, "—"],
    [0, "0.0 ms"],
    [4.38, "4.4 ms"],
    [99.94, "99.9 ms"],
    [123.6, "124 ms"],
    [1234, "1.2 s"],
    [12_345, "12 s"],
  ])("%s -> %s", (input, expected) => {
    expect(formatMs(input)).toBe(expected);
  });
});

describe("formatCount", () => {
  it.each([
    [0, "0"],
    [999, "999"],
    [1000, "1K"],
    [1284, "1.3K"],
    [12_900, "12.9K"],
    [4_200_000, "4.2M"],
  ])("%s -> %s", (input, expected) => {
    expect(formatCount(input)).toBe(expected);
  });
});

describe("formatDuration", () => {
  it.each([
    [0, "0s"],
    [59, "59s"],
    [61, "1m 1s"],
    [3_660, "1h 1m"],
    [90_000, "1d 1h"],
    [-5, "0s"],
  ])("%s s -> %s", (input, expected) => {
    expect(formatDuration(input)).toBe(expected);
  });
});

describe("formatRelative", () => {
  const now = Date.parse("2026-10-21T06:00:00Z");
  it("handles never, now and past", () => {
    expect(formatRelative(null, now)).toBe("never");
    expect(formatRelative("2026-10-21T05:59:58Z", now)).toBe("just now");
    expect(formatRelative("2026-10-21T05:59:30Z", now)).toBe("30s ago");
    expect(formatRelative("2026-10-21T05:00:00Z", now)).toBe("1h 0m ago");
  });
});

describe("niceTicks", () => {
  it.each([
    [4.0, [0, 1, 2, 3, 4]],
    [10.2, [0, 5, 10, 15]],
    [5, [0, 2, 4, 6]],
    [0.4, [0, 0.1, 0.2, 0.3, 0.4]],
    [350, [0, 100, 200, 300, 400]],
    [1234, [0, 500, 1000, 1500]],
    [0, [0, 0.25, 0.5, 0.75, 1]],
  ])("max %s -> %j", (max, expected) => {
    expect(niceTicks(max)).toEqual(expected);
  });

  it("always yields clean, evenly spaced ticks that cover the max", () => {
    for (const max of [0.07, 1.3, 2.9, 7.7, 13, 48, 99, 101, 777, 5001]) {
      const ticks = niceTicks(max);
      const step = ticks[1] - ticks[0];
      expect(ticks[0]).toBe(0);
      expect(ticks[ticks.length - 1]).toBeGreaterThanOrEqual(max);
      expect(ticks.length).toBeGreaterThanOrEqual(3);
      expect(ticks.length).toBeLessThanOrEqual(6);
      const mantissa = step / 10 ** Math.floor(Math.log10(step));
      expect([1, 2, 2.5, 5]).toContain(Number(mantissa.toFixed(6)));
    }
  });
});

describe("percentile", () => {
  it("uses nearest rank", () => {
    expect(percentile([], 95)).toBeNull();
    expect(percentile([5], 95)).toBe(5);
    const values = Array.from({ length: 100 }, (_, i) => i + 1);
    expect(percentile(values, 95)).toBe(95);
    expect(percentile(values, 50)).toBe(50);
    expect(percentile([3, 1, 2], 100)).toBe(3);
  });
});
