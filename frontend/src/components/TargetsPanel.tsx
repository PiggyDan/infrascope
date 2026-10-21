import { useState, type FormEvent, type KeyboardEvent, type MouseEvent } from "react";

import { ApiError, type ApiClient } from "../api";
import { formatRelative } from "../format";
import type { Target } from "../types";
import { StatusBadge } from "./StatusBadge";

interface Props {
  client: ApiClient;
  targets: Target[] | null;
  isAdmin: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onChanged: () => void;
  now: number;
}

function messageOf(err: unknown): string {
  return err instanceof ApiError ? err.message : "Request failed";
}

function AddTargetForm({ client, onCreated }: { client: ApiClient; onCreated: (t: Target) => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("http://testtarget:8080/healthy");
  const [interval, setIntervalSeconds] = useState(30);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await client.createTarget({ name: name.trim(), url: url.trim(), interval_seconds: interval });
      setName("");
      onCreated(created);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} aria-label="Add target">
      <div className="form-row">
        <div className="field">
          <label htmlFor="t-name">Name</label>
          <input id="t-name" type="text" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} />
        </div>
        <div className="field">
          <label htmlFor="t-url">URL (allowlisted hosts only)</label>
          <input id="t-url" type="text" value={url} onChange={(e) => setUrl(e.target.value)} required maxLength={2048} spellCheck={false} />
        </div>
        <div className="field">
          <label htmlFor="t-interval">Interval (s)</label>
          <input
            id="t-interval"
            type="number"
            min={5}
            max={3600}
            value={interval}
            onChange={(e) => setIntervalSeconds(Number(e.target.value))}
            required
          />
        </div>
        <button className="btn primary" type="submit" disabled={busy || !name.trim()}>
          {busy ? "Adding…" : "Add target"}
        </button>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

export function TargetsPanel({ client, targets, isAdmin, selectedId, onSelect, onChanged, now }: Props) {
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(id: string, action: () => Promise<unknown>) {
    setBusyId(id);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusyId(null);
      setConfirmingId(null);
    }
  }

  const stop = (event: MouseEvent) => event.stopPropagation();
  const onRowKey = (event: KeyboardEvent, id: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(id);
    }
  };

  return (
    <section className="card" aria-labelledby="targets-h">
      <div className="card-head">
        <h2 id="targets-h">Targets</h2>
        {!isAdmin && <span className="muted">Read-only (VIEWER key)</span>}
      </div>
      <p className="sub">Click a target to see its response times and check history.</p>
      {isAdmin && (
        <AddTargetForm
          client={client}
          onCreated={(created) => {
            onChanged();
            onSelect(created.id);
          }}
        />
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Name</th>
              <th className="num hide-sm">Every</th>
              <th>Last check</th>
              <th>Monitoring</th>
              {isAdmin && <th aria-label="Actions" />}
            </tr>
          </thead>
          <tbody>
            {targets === null && (
              <tr>
                <td colSpan={6} className="empty">Loading…</td>
              </tr>
            )}
            {targets?.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No targets yet{isAdmin ? ". Add one above." : "."}
                </td>
              </tr>
            )}
            {targets?.map((target) => (
              <tr
                key={target.id}
                className={`selectable${target.id === selectedId ? " selected" : ""}`}
                onClick={() => onSelect(target.id)}
                onKeyDown={(e) => onRowKey(e, target.id)}
                tabIndex={0}
                aria-selected={target.id === selectedId}
              >
                <td>
                  <StatusBadge status={target.enabled ? target.status : "PAUSED"} />
                </td>
                <td>
                  <div>{target.name}</div>
                  <div className="url truncate" title={target.url}>
                    {target.url}
                  </div>
                </td>
                <td className="num hide-sm">{target.interval_seconds}s</td>
                <td className="muted">{formatRelative(target.last_checked_at, now)}</td>
                <td onClick={stop}>
                  <button
                    type="button"
                    role="switch"
                    className="switch"
                    aria-checked={target.enabled}
                    aria-label={`Monitoring for ${target.name}`}
                    disabled={!isAdmin || busyId === target.id}
                    onClick={() => act(target.id, () => client.updateTarget(target.id, { enabled: !target.enabled }))}
                  />
                </td>
                {isAdmin && (
                  <td className="num" onClick={stop}>
                    {confirmingId === target.id ? (
                      <>
                        <button
                          type="button"
                          className="btn small danger"
                          disabled={busyId === target.id}
                          onClick={() => act(target.id, () => client.deleteTarget(target.id))}
                        >
                          Delete
                        </button>{" "}
                        <button type="button" className="btn small" onClick={() => setConfirmingId(null)}>
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="btn small"
                        aria-label={`Delete ${target.name}`}
                        onClick={() => setConfirmingId(target.id)}
                      >
                        Delete…
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
