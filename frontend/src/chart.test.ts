import { describe, expect, it } from "vitest";

import { areaPath, evenTicks, linePath, linearScale, nearestIndex, segments, toPoints } from "./chart";
import type { CheckResult } from "./types";

function result(second: number, ms: number | null, success = true): CheckResult {
  return {
    id: `r${second}`,
    target_id: "t",
    checked_at: new Date(Date.UTC(2026, 9, 21, 6, 0, second)).toISOString(),
    success,
    status_code: success ? 200 : 503,
    response_time_ms: ms,
    error: success ? null : "HTTP 503",
  };
}

describe("toPoints", () => {
  it("orders newest-first API results chronologically", () => {
    const points = toPoints([result(20, 3), result(10, 2), result(0, 1)]);
    expect(points.map((p) => p.v)).toEqual([1, 2, 3]);
  });
});

describe("segments / paths", () => {
  const points = toPoints([result(0, 10), result(5, 20), result(10, null, false), result(15, 30), result(20, 40)]);
  const x = linearScale(points[0].t, points[4].t, 0, 100);
  const y = linearScale(0, 40, 100, 0);

  it("breaks the line where no response arrived", () => {
    expect(segments(points).map((run) => run.map((p) => p.v))).toEqual([
      [10, 20],
      [30, 40],
    ]);
  });

  it("draws one subpath per segment", () => {
    expect(linePath(points, x, y)).toBe("M0.0,75.0L25.0,50.0M75.0,25.0L100.0,0.0");
  });

  it("closes each area segment on the baseline", () => {
    const d = areaPath(points, x, y, 100);
    expect(d).toBe("M0.0,100L0.0,75.0L25.0,50.0L25.0,100ZM75.0,100L75.0,25.0L100.0,0.0L100.0,100Z");
  });

  it("skips single-point area segments", () => {
    const lonely = toPoints([result(0, 10), result(5, null, false), result(10, 20)]);
    expect(areaPath(lonely, x, y, 100)).toBe("");
  });
});

describe("linearScale", () => {
  it("maps domain to range and survives a zero-width domain", () => {
    expect(linearScale(0, 10, 100, 200)(5)).toBe(150);
    expect(Number.isFinite(linearScale(5, 5, 0, 100)(5))).toBe(true);
  });
});

describe("nearestIndex", () => {
  const xs = [0, 10, 20, 30];
  it.each([
    [-5, 0],
    [4, 0],
    [6, 1],
    [15, 1],
    [16, 2],
    [99, 3],
  ])("%s -> %s", (px, expected) => {
    expect(nearestIndex(xs, px)).toBe(expected);
  });
  it("returns -1 for no points", () => {
    expect(nearestIndex([], 5)).toBe(-1);
  });
});

describe("evenTicks", () => {
  it("spreads ticks evenly including both ends", () => {
    expect(evenTicks(0, 100, 5)).toEqual([0, 25, 50, 75, 100]);
    expect(evenTicks(3, 3, 4)).toEqual([3]);
  });
});
