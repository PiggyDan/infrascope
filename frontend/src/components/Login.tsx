import { useState, type FormEvent } from "react";

import { ApiError, createClient } from "../api";
import type { ApiKeyInfo } from "../types";

interface Props {
  notice: string | null;
  onLogin: (apiKey: string, info: ApiKeyInfo) => void;
}

export function Login({ notice, onLogin }: Props) {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const candidate = key.trim();
    if (!candidate) return;
    setBusy(true);
    setError(null);
    try {
      const info = await createClient(candidate).me();
      onLogin(candidate, info);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "That key was not accepted. It may be mistyped, expired or revoked."
          : "Could not reach the InfraScope API. Is the stack running?",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <div className="card">
        <img src="/favicon.svg" alt="" width={36} height={36} />
        <h1>Sign in to InfraScope</h1>
        <p>Paste an API key. VIEWER keys can look; ADMIN keys can also change targets.</p>
        {notice && <div className="notice error">{notice}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="api-key">API key</label>
            <input
              id="api-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="isk_…"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              autoFocus
            />
          </div>
          {error && (
            <div className="notice error" role="alert">
              {error}
            </div>
          )}
          <button className="btn primary" type="submit" disabled={busy || !key.trim()}>
            {busy ? "Checking…" : "Sign in"}
          </button>
        </form>
        <p className="fine-print">
          No key yet? Run <code>docker compose exec api python -m app.cli create-api-key --name me --role ADMIN</code>.
          The key is kept in this browser tab only and is cleared when you close it.
        </p>
      </div>
    </main>
  );
}
