import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { areaPath, evenTicks, linePath, linearScale, nearestIndex, toPoints } from "../chart";
import { formatMs, formatTime, niceTicks } from "../format";
import type { CheckResult } from "../types";

const HEIGHT = 200;
const MARGIN = { top: 14, right: 64, bottom: 26, left: 52 };

export function ResponseTimeChart({ results, title }: { results: CheckResult[]; title: string }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [active, setActive] = useState<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const points = useMemo(() => toPoints(results), [results]);
  const geometry = useMemo(() => {
    if (points.length === 0) return null;
    const t0 = points[0].t;
    const t1 = points.length > 1 ? points[points.length - 1].t : t0 + 1000;
    const values = points.map((p) => p.v).filter((v): v is number => v !== null);
    const yTicks = niceTicks(Math.max(0, ...values));
    const yMax = yTicks[yTicks.length - 1];
    const x = linearScale(t0, t1, MARGIN.left, width - MARGIN.right);
    const y = linearScale(0, yMax, HEIGHT - MARGIN.bottom, MARGIN.top);
    return {
      x,
      y,
      xs: points.map((p) => x(p.t)),
      yTicks,
      xTicks: evenTicks(t0, t1, width < 480 ? 3 : 4),
      baseline: HEIGHT - MARGIN.bottom,
    };
  }, [points, width]);

  if (!geometry) {
    return (
      <div className="chart" ref={wrapRef}>
        <div className="empty">No checks yet. The first result appears within one interval.</div>
      </div>
    );
  }

  const { x, y, xs, yTicks, xTicks, baseline } = geometry;
  const failures = points.filter((p) => !p.ok);
  const last = points[points.length - 1];
  const activePoint = active !== null ? points[active] : null;
  const pointY = (v: number | null) => (v === null ? baseline : y(v));

  function onPointerMove(event: PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    setActive(nearestIndex(xs, event.clientX - rect.left));
  }

  function onKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    const current = active ?? points.length - 1;
    if (event.key === "ArrowLeft") setActive(Math.max(0, current - 1));
    else if (event.key === "ArrowRight") setActive(Math.min(points.length - 1, current + 1));
    else if (event.key === "Home") setActive(0);
    else if (event.key === "End") setActive(points.length - 1);
    else if (event.key === "Escape") setActive(null);
    else return;
    event.preventDefault();
  }

  const description =
    `${title}: ${points.length} checks from ${formatTime(points[0].result.checked_at)} ` +
    `to ${formatTime(last.result.checked_at)}, latest ${formatMs(last.v)}, ${failures.length} failed. ` +
    "Use arrow keys to step through checks; the table below lists every value.";

  return (
    <div className="chart" ref={wrapRef}>
      <div className="legend" aria-hidden="true">
        <span className="key">
          <span className="line-key" /> Response time
        </span>
        <span className="key">
          <span className="dot-key" /> Failed check
        </span>
      </div>
      <svg
        width={width}
        height={HEIGHT}
        role="img"
        aria-label={description}
        tabIndex={0}
        onPointerMove={onPointerMove}
        onPointerLeave={() => setActive(null)}
        onFocus={() => setActive(points.length - 1)}
        onBlur={() => setActive(null)}
        onKeyDown={onKeyDown}
      >
        {yTicks.map((tick) => (
          <g key={`y${tick}`}>
            {tick > 0 && (
              <line className="gridline" x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} />
            )}
            <text className="tick" x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
              {formatMs(tick)}
            </text>
          </g>
        ))}
        <line className="baseline" x1={MARGIN.left} x2={width - MARGIN.right} y1={baseline} y2={baseline} />
        {xTicks.map((tick, i) => (
          <text
            key={`x${tick}`}
            className="tick"
            x={x(tick)}
            y={HEIGHT - 6}
            textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"}
          >
            {formatTime(new Date(tick).toISOString())}
          </text>
        ))}

        <path className="area" d={areaPath(points, x, y, baseline)} />
        <path className="line" d={linePath(points, x, y)} />

        {failures.map((p) => (
          <circle key={p.result.id} className="fail-dot" cx={x(p.t)} cy={pointY(p.v)} r={4} />
        ))}

        {/* End label: the latest value, the one number the reader wants. */}
        {last.v !== null && (
          <>
            {last.ok && <circle className="focus-dot" cx={x(last.t)} cy={y(last.v)} r={4} />}
            <text className="end-label" x={x(last.t) + 10} y={y(last.v)} dy="0.32em">
              {formatMs(last.v)}
            </text>
          </>
        )}

        {activePoint && (
          <g aria-hidden="true">
            <line className="crosshair" x1={xs[active!]} x2={xs[active!]} y1={MARGIN.top} y2={baseline} />
            <circle
              className={activePoint.ok ? "focus-dot" : "fail-dot"}
              cx={xs[active!]}
              cy={pointY(activePoint.v)}
              r={5}
            />
          </g>
        )}
      </svg>

      {activePoint && (
        <div className="tooltip" style={{ left: xs[active!], top: pointY(activePoint.v) }} role="status">
          <strong>{activePoint.v === null ? "No response" : formatMs(activePoint.v)}</strong>
          <span className="t-sub">
            {formatTime(activePoint.result.checked_at)} ·{" "}
            {activePoint.ok
              ? `HTTP ${activePoint.result.status_code}`
              : (activePoint.result.error ?? "Failed")}
          </span>
        </div>
      )}
    </div>
  );
}
