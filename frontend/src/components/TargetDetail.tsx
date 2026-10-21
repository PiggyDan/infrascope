import { useCallback } from "react";

import type { ApiClient } from "../api";
import { formatMs, formatTime, percentile } from "../format";
import { usePolling } from "../hooks";
import type { Target } from "../types";
import { ResponseTimeChart } from "./ResponseTimeChart";
import { StatusBadge } from "./StatusBadge";

const RESULT_LIMIT = 120;
const TABLE_ROWS = 15;

export function TargetDetail({ client, target }: { client: ApiClient; target: Target }) {
  const fetchResults = useCallback(() => client.results(target.id, RESULT_LIMIT), [client, target.id]);
  const { data: results, loading, error } = usePolling(fetchResults, 5000);

  const times = (results ?? []).map((r) => r.response_time_ms).filter((v): v is number => v !== null);
  const successes = (results ?? []).filter((r) => r.success).length;
  const uptime = results && results.length ? (successes / results.length) * 100 : null;
  const avg = times.length ? times.reduce((a, b) => a + b, 0) / times.length : null;

  return (
    <section className={`card${loading && results ? " refetching" : ""}`} aria-labelledby="detail-h">
      <div className="card-head">
        <h2 id="detail-h">{target.name}</h2>
        <StatusBadge status={target.enabled ? target.status : "PAUSED"} />
      </div>
      <p className="sub url">{target.url}</p>

      {error && <p className="error-text">Could not load results: {error.message}</p>}

      <div className="stats-row">
        <div>
          Uptime (last {results?.length ?? 0} checks)
          <b>{uptime === null ? "—" : `${Number.isInteger(uptime) ? uptime : uptime.toFixed(1)}%`}</b>
        </div>
        <div>
          Average
          <b>{formatMs(avg)}</b>
        </div>
        <div>
          p95
          <b>{formatMs(percentile(times, 95))}</b>
        </div>
        <div>
          Consecutive failures
          <b>{target.consecutive_failures}</b>
        </div>
      </div>

      <h3 className="sub">Response time</h3>
      {results === null ? (
        <div className="empty">Loading…</div>
      ) : (
        <ResponseTimeChart results={results} title={`Response time for ${target.name}`} />
      )}

      <h3 className="sub section-gap">Recent checks</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Result</th>
              <th className="num">HTTP</th>
              <th className="num">Response</th>
            </tr>
          </thead>
          <tbody>
            {results?.length === 0 && (
              <tr>
                <td colSpan={4} className="empty">No checks yet.</td>
              </tr>
            )}
            {results?.slice(0, TABLE_ROWS).map((r) => (
              <tr key={r.id}>
                <td className="time">{formatTime(r.checked_at)}</td>
                <td>
                  <StatusBadge status={r.success ? "CHECK_OK" : "CHECK_FAILED"} />
                  {/* "HTTP 503" would repeat the HTTP column; timeouts/connection errors add information. */}
                  {r.error && r.status_code === null && <div className="muted">{r.error}</div>}
                </td>
                <td className="num">{r.status_code ?? "—"}</td>
                <td className="num">{formatMs(r.response_time_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
