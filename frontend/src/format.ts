/** Display helpers. Pure functions so they can be unit-tested. */

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10_000 ? 0 : 1)} s`;
  if (ms >= 100) return `${Math.round(ms)} ms`;
  return `${ms.toFixed(1)} ms`;
}

export function formatCount(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${trim(n / 1_000_000)}M`;
  if (Math.abs(n) >= 1_000) return `${trim(n / 1_000)}K`;
  return String(n);
}

function trim(value: number): string {
  return value.toFixed(value >= 100 ? 0 : 1).replace(/\.0$/, "");
}

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

export function formatRelative(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "never";
  const seconds = (now - Date.parse(iso)) / 1000;
  if (seconds < 5) return "just now";
  return `${formatDuration(seconds)} ago`;
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/**
 * Axis ticks from 0 that land on clean numbers: the step is 1, 2, 2.5 or 5 × 10^n,
 * chosen so roughly four intervals cover `max`. (Splitting a "nice" max into fixed
 * quarters gives ticks like 1.25 and 3.75, which display as 1.3 / 3.8.)
 */
export function niceTicks(max: number, targetIntervals = 4): number[] {
  const value = max > 0 ? max : 1;
  const raw = value / targetIntervals;
  const exponent = Math.floor(Math.log10(raw));
  const base = 10 ** exponent;
  const step = [1, 2, 2.5, 5, 10].map((m) => m * base).find((s) => s >= raw)!;
  const count = Math.ceil(value / step - 1e-9);
  // Round away floating-point noise (0.30000000000000004 → 0.3).
  const decimals = Math.max(0, -exponent + 1);
  return Array.from({ length: count + 1 }, (_, i) => Number((i * step).toFixed(decimals)));
}

/** Percentile (0–100) using nearest-rank. Returns null for an empty list. */
export function percentile(values: number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.ceil((p / 100) * sorted.length);
  return sorted[Math.min(sorted.length - 1, Math.max(0, rank - 1))];
}
