import { formatDateTime, formatDuration } from "../format";
import type { Incident } from "../types";
import { StatusBadge } from "./StatusBadge";

export function sortIncidents(incidents: Incident[]): Incident[] {
  // Open incidents first, then newest first.
  return [...incidents].sort((a, b) => {
    if (a.status !== b.status) return a.status === "OPEN" ? -1 : 1;
    return Date.parse(b.opened_at) - Date.parse(a.opened_at);
  });
}

export function IncidentsPanel({ incidents, now }: { incidents: Incident[] | null; now: number }) {
  return (
    <section className="card" aria-labelledby="incidents-h">
      <h2 id="incidents-h">Incidents</h2>
      <p className="sub">Opened after 2 consecutive failed checks, resolved after 2 consecutive successes.</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Target</th>
              <th>Opened</th>
              <th className="num">Duration</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {incidents === null && (
              <tr>
                <td colSpan={5} className="empty">Loading…</td>
              </tr>
            )}
            {incidents?.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">No incidents. Everything has been healthy.</td>
              </tr>
            )}
            {incidents &&
              sortIncidents(incidents).map((incident) => {
                const end = incident.resolved_at ? Date.parse(incident.resolved_at) : now;
                const duration = formatDuration((end - Date.parse(incident.opened_at)) / 1000);
                return (
                  <tr key={incident.id}>
                    <td>
                      <StatusBadge status={incident.status} />
                    </td>
                    <td className="nowrap">
                      {incident.target_name}
                      {incident.target_id === null && <span className="muted"> (deleted)</span>}
                    </td>
                    <td className="muted nowrap">{formatDateTime(incident.opened_at)}</td>
                    <td className="num">
                      {duration}
                      {!incident.resolved_at && <span className="muted"> ongoing</span>}
                    </td>
                    <td title={incident.resolution_reason ?? undefined}>
                      {incident.failure_reason}
                      {/* Normal recovery is already said by the badge; only show unusual resolutions. */}
                      {incident.resolution_reason && !incident.resolution_reason.startsWith("Recovered") && (
                        <div className="muted">{incident.resolution_reason}</div>
                      )}
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
