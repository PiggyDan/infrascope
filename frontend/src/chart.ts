/** Pure geometry helpers for the response-time chart (unit-tested in chart.test.ts). */
import type { CheckResult } from "./types";

export interface Point {
  t: number; // epoch ms
  v: number | null; // response time ms; null when no HTTP response arrived
  ok: boolean;
  result: CheckResult;
}

/** API returns newest first; the chart wants oldest → newest. */
export function toPoints(results: CheckResult[]): Point[] {
  return results
    .map((r) => ({ t: Date.parse(r.checked_at), v: r.response_time_ms, ok: r.success, result: r }))
    .sort((a, b) => a.t - b.t);
}

export function linearScale(d0: number, d1: number, r0: number, r1: number) {
  const span = d1 - d0 || 1;
  return (value: number) => r0 + ((value - d0) / span) * (r1 - r0);
}

/** Contiguous runs of points that have a value; a null value breaks the line. */
export function segments(points: Point[]): Point[][] {
  const runs: Point[][] = [];
  let current: Point[] = [];
  for (const point of points) {
    if (point.v === null) {
      if (current.length) runs.push(current);
      current = [];
    } else {
      current.push(point);
    }
  }
  if (current.length) runs.push(current);
  return runs;
}

type Scale = (value: number) => number;

export function linePath(points: Point[], x: Scale, y: Scale): string {
  return segments(points)
    .map((run) =>
      run.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t).toFixed(1)},${y(p.v!).toFixed(1)}`).join(""),
    )
    .join("");
}

export function areaPath(points: Point[], x: Scale, y: Scale, baselineY: number): string {
  return segments(points)
    .filter((run) => run.length > 1)
    .map((run) => {
      const top = run.map((p) => `L${x(p.t).toFixed(1)},${y(p.v!).toFixed(1)}`).join("");
      const x0 = x(run[0].t).toFixed(1);
      const x1 = x(run[run.length - 1].t).toFixed(1);
      return `M${x0},${baselineY}${top}L${x1},${baselineY}Z`;
    })
    .join("");
}

/** Index of the value in a sorted array closest to `target` (binary search). */
export function nearestIndex(sorted: number[], target: number): number {
  if (sorted.length === 0) return -1;
  let lo = 0;
  let hi = sorted.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid] <= target) lo = mid;
    else hi = mid;
  }
  return Math.abs(sorted[lo] - target) <= Math.abs(sorted[hi] - target) ? lo : hi;
}

export function evenTicks(min: number, max: number, count: number): number[] {
  if (count < 2 || max === min) return [min];
  return Array.from({ length: count }, (_, i) => min + ((max - min) * i) / (count - 1));
}
