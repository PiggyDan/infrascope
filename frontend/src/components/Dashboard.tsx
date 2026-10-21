import { useCallback, useState } from "react";

import type { ApiClient } from "../api";
import { formatTime } from "../format";
import { useNow, usePolling } from "../hooks";
import type { ApiKeyInfo } from "../types";
import { IncidentsPanel } from "./IncidentsPanel";
import { SummaryTiles } from "./SummaryTiles";
import { TargetDetail } from "./TargetDetail";
import { TargetsPanel } from "./TargetsPanel";

const REFRESH_MS = 5000;

interface Props {
  client: ApiClient;
  me: ApiKeyInfo;
  onLogout: () => void;
}

export function Dashboard({ client, me, onLogout }: Props) {
  const now = useNow();
  const summary = usePolling(useCallback(() => client.summary(), [client]), REFRESH_MS);
  const targets = usePolling(useCallback(() => client.targets(), [client]), REFRESH_MS);
  const incidents = usePolling(useCallback(() => client.incidents(50), [client]), REFRESH_MS);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = targets.data?.find((t) => t.id === selectedId) ?? targets.data?.[0] ?? null;
  const refreshAll = () => {
    summary.refresh();
    targets.refresh();
    incidents.refresh();
  };
  const lastUpdated = summary.data ? formatTime(summary.data.generated_at) : null;
  const loadError = summary.error ?? targets.error ?? incidents.error;

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" alt="" />
          <h1>InfraScope</h1>
        </div>
        <div className="session">
          <span className="refresh-note" aria-live="polite">
            {loadError
              ? `Update failed: ${loadError.message}`
              : lastUpdated
                ? `Auto-refresh every ${REFRESH_MS / 1000}s · updated ${lastUpdated}`
                : "Loading…"}
          </span>
          <span>
            {me.name} · <strong>{me.role}</strong>
          </span>
          <button className="btn small" type="button" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>

      <SummaryTiles summary={summary.data} />

      <div className="grid-main">
        <div className="stack">
          <TargetsPanel
            client={client}
            targets={targets.data}
            isAdmin={me.role === "ADMIN"}
            selectedId={selected?.id ?? null}
            onSelect={setSelectedId}
            onChanged={refreshAll}
            now={now}
          />
          <IncidentsPanel incidents={incidents.data} now={now} />
        </div>
        <div className="stack">
          {selected ? (
            // key: remount per target so one target's results never show under another's name.
            <TargetDetail key={selected.id} client={client} target={selected} />
          ) : (
            <section className="card">
              <h2>No target selected</h2>
              <p className="sub">Register a target to start monitoring.</p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
