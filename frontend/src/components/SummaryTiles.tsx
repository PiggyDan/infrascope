import { formatCount, formatMs } from "../format";
import type { Summary } from "../types";
import { StatusBadge } from "./StatusBadge";

export function SummaryTiles({ summary }: { summary: Summary | null }) {
  if (!summary) {
    return <div className="tiles" aria-busy="true" />;
  }
  const by = summary.targets_by_status;
  return (
    <section className="tiles" aria-label="Summary">
      <div className="card tile">
        <div className="label">Targets</div>
        <div className="value">{summary.targets_total}</div>
        <div className="detail">{summary.targets_enabled} monitored</div>
      </div>
      <div className="card tile">
        <div className="label">
          <StatusBadge status="UP" />
        </div>
        <div className="value">{by.UP}</div>
        <div className="detail">{by.UNKNOWN} not yet checked</div>
      </div>
      <div className="card tile">
        <div className="label">
          <StatusBadge status="DOWN" />
        </div>
        <div className="value">{by.DOWN}</div>
        <div className="detail">confirmed after 2 failed checks</div>
      </div>
      <div className="card tile">
        <div className="label">Open incidents</div>
        <div className="value">{summary.open_incidents}</div>
        <div className="detail">{summary.open_incidents === 0 ? "all clear" : "needs attention"}</div>
      </div>
      <div className="card tile">
        <div className="label">Checks, last 24h</div>
        <div className="value">{formatCount(summary.checks_last_24h)}</div>
        <div className="detail">{formatCount(summary.failed_checks_last_24h)} failed</div>
      </div>
      <div className="card tile">
        <div className="label">Avg response, last 24h</div>
        <div className="value">{formatMs(summary.avg_response_time_ms_last_24h)}</div>
        <div className="detail">time to response headers</div>
      </div>
    </section>
  );
}
