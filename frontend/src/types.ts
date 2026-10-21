// Mirrors the backend Pydantic schemas (app/schemas.py).

export type TargetStatus = "UP" | "DOWN" | "UNKNOWN";
export type IncidentStatus = "OPEN" | "RESOLVED";
export type ApiKeyRole = "VIEWER" | "ADMIN";

export interface Target {
  id: string;
  name: string;
  url: string;
  target_type: "HTTP";
  interval_seconds: number;
  enabled: boolean;
  status: TargetStatus;
  consecutive_failures: number;
  consecutive_successes: number;
  created_at: string;
  updated_at: string;
  last_checked_at: string | null;
}

export interface CheckResult {
  id: string;
  target_id: string;
  checked_at: string;
  success: boolean;
  status_code: number | null;
  response_time_ms: number | null;
  error: string | null;
}

export interface Incident {
  id: string;
  target_id: string | null;
  target_name: string;
  status: IncidentStatus;
  opened_at: string;
  resolved_at: string | null;
  failure_reason: string;
  resolution_reason: string | null;
}

export interface Summary {
  targets_total: number;
  targets_enabled: number;
  targets_by_status: Record<TargetStatus, number>;
  open_incidents: number;
  checks_last_24h: number;
  failed_checks_last_24h: number;
  avg_response_time_ms_last_24h: number | null;
  generated_at: string;
}

export interface ApiKeyInfo {
  id: string;
  name: string;
  key_prefix: string;
  role: ApiKeyRole;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface TargetInput {
  name: string;
  url: string;
  interval_seconds: number;
}
