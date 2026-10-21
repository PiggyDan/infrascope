import { useCallback, useEffect, useRef, useState } from "react";

export interface Polled<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  refresh: () => void;
}

/**
 * Fetch now, then every `intervalMs`. Keeps the previous data while refetching
 * (no flashing), and skips work while the tab is hidden.
 */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number): Polled<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const run = async () => {
      if (document.hidden) {
        timer = setTimeout(run, intervalMs);
        return;
      }
      setLoading(true);
      try {
        const next = await fetcherRef.current();
        if (!cancelled) {
          setData(next);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err as Error);
      } finally {
        if (!cancelled) {
          setLoading(false);
          timer = setTimeout(run, intervalMs);
        }
      }
    };
    run();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [intervalMs, tick]);

  const refresh = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, refresh };
}

/** Re-render every `intervalMs` so relative times ("12s ago") stay current. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
