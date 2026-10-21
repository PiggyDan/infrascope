import { useCallback, useEffect, useMemo, useState } from "react";

import { createClient } from "./api";
import { Dashboard } from "./components/Dashboard";
import { Login } from "./components/Login";
import type { ApiKeyInfo } from "./types";

// sessionStorage: survives reloads, cleared when the tab closes, never sent anywhere
// except as the X-API-Key header to our own origin. The strict CSP (no third-party
// or inline scripts) limits what could ever read it.
const STORAGE_KEY = "infrascope.apiKey";

function readStoredKey(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeKey(key: string | null) {
  try {
    if (key) sessionStorage.setItem(STORAGE_KEY, key);
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage unavailable (private mode): the session just won't survive a reload.
  }
}

export default function App() {
  const [apiKey, setApiKey] = useState<string | null>(readStoredKey);
  const [me, setMe] = useState<ApiKeyInfo | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const logout = useCallback((message: string | null = null) => {
    storeKey(null);
    setApiKey(null);
    setMe(null);
    setNotice(message);
  }, []);

  const client = useMemo(() => {
    if (!apiKey) return null;
    // Any 401 means the key was revoked or expired mid-session: send the user back to sign-in.
    const guardedFetch: typeof fetch = async (input, init) => {
      const response = await fetch(input, init);
      if (response.status === 401) logout("Your API key is no longer valid. Please sign in again.");
      return response;
    };
    return createClient(apiKey, guardedFetch);
  }, [apiKey, logout]);

  useEffect(() => {
    if (client && !me) client.me().then(setMe).catch(() => undefined);
  }, [client, me]);

  if (!client) {
    return (
      <Login
        notice={notice}
        onLogin={(key, info) => {
          storeKey(key);
          setApiKey(key);
          setMe(info);
          setNotice(null);
        }}
      />
    );
  }
  if (!me) {
    return (
      <main className="login">
        <p className="muted">Loading…</p>
      </main>
    );
  }
  return <Dashboard client={client} me={me} onLogout={() => logout()} />;
}
