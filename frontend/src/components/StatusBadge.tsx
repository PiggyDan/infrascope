import type { IncidentStatus, TargetStatus } from "../types";

type BadgeKind = TargetStatus | IncidentStatus | "PAUSED" | "CHECK_OK" | "CHECK_FAILED";

// Status is never carried by color alone: every badge has an icon and a text label.
const BADGES: Record<BadgeKind, { className: string; icon: string; label: string }> = {
  UP: { className: "up", icon: "✓", label: "Up" },
  DOWN: { className: "down", icon: "✕", label: "Down" },
  UNKNOWN: { className: "unknown", icon: "?", label: "Unknown" },
  PAUSED: { className: "paused", icon: "‖", label: "Paused" },
  OPEN: { className: "open", icon: "!", label: "Open" },
  RESOLVED: { className: "resolved", icon: "✓", label: "Resolved" },
  CHECK_OK: { className: "up", icon: "✓", label: "OK" },
  CHECK_FAILED: { className: "down", icon: "✕", label: "Failed" },
};

export function StatusBadge({ status }: { status: BadgeKind }) {
  const badge = BADGES[status];
  return (
    <span className={`badge ${badge.className}`}>
      <span className="icon" aria-hidden="true">
        {badge.icon}
      </span>
      {badge.label}
    </span>
  );
}
