import { Shield } from "lucide-react";
import { useWatchdogEvents } from "../../hooks/useWatchdog";
import type { WatchdogEvent } from "../../types/watchdog";

interface WatchdogPanelProps {
  theme: "dark" | "light";
}

function eventColor(eventType: string): {
  bg: string;
  fg: string;
  border: string;
  dot: string;
} {
  switch (eventType) {
    case "down":
    case "restart_failed":
    case "check_error":
      return {
        bg: "bg-rose-500/15",
        fg: "text-rose-400",
        border: "border-rose-500/30",
        dot: "bg-rose-400",
      };
    case "restored":
    case "restart_succeeded":
      return {
        bg: "bg-emerald-500/15",
        fg: "text-emerald-400",
        border: "border-emerald-500/30",
        dot: "bg-emerald-400",
      };
    case "restart_triggered":
    case "degraded":
      return {
        bg: "bg-amber-500/15",
        fg: "text-amber-400",
        border: "border-amber-500/30",
        dot: "bg-amber-400",
      };
    default:
      return {
        bg: "bg-white/10",
        fg: "text-white/60",
        border: "border-white/20",
        dot: "bg-white/40",
      };
  }
}

function relativeSecsAgo(iso: string): string {
  const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export function WatchdogPanel({ theme }: WatchdogPanelProps) {
  const isDark = theme === "dark";
  const border = isDark ? "border-white/10" : "border-[#141414]/10";
  const subtle = isDark ? "bg-white/5" : "bg-[#141414]/5";
  const fg = isDark ? "text-white/85" : "text-[#141414]/85";
  const muted = isDark ? "text-white/40" : "text-[#141414]/45";

  const { data, error } = useWatchdogEvents(10);
  const events: WatchdogEvent[] = data?.events ?? [];

  const recentDowns = events.filter((e) =>
    ["down", "restart_failed", "check_error"].includes(e.event_type),
  ).length;
  const isHealthy = recentDowns === 0;

  const headerColors = isHealthy
    ? {
        bg: "bg-emerald-500/15",
        fg: "text-emerald-400",
        border: "border-emerald-500/30",
        dot: "bg-emerald-400",
      }
    : {
        bg: "bg-amber-500/15",
        fg: "text-amber-400",
        border: "border-amber-500/30",
        dot: "bg-amber-400",
      };

  return (
    <div className={`rounded-xl border ${border} ${subtle} px-3 py-2`}>
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <Shield className={`w-3 h-3 ${isHealthy ? "text-emerald-400" : "text-amber-400"}`} />
          <p className="text-[9px] font-mono uppercase opacity-40">SELF-HEALING WATCHDOG</p>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded border text-[9px] font-mono font-bold ${headerColors.bg} ${headerColors.fg} ${headerColors.border}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${headerColors.dot}`} />
          {isHealthy ? "ALL SERVICES NOMINAL" : `${recentDowns} INCIDENT${recentDowns > 1 ? "S" : ""}`}
        </div>
      </div>

      {error ? (
        <p className="text-[9px] font-mono text-rose-400">Error loading watchdog events</p>
      ) : events.length === 0 ? (
        <p className={`text-[9px] font-mono ${muted}`}>No incidents — services running clean</p>
      ) : (
        <div className="flex flex-col gap-1">
          {events.slice(0, 5).map((e) => {
            const colors = eventColor(e.event_type);
            return (
              <div
                key={e.id}
                className={`flex items-center justify-between gap-2 px-2 py-1 rounded-lg border ${colors.border} ${isDark ? "bg-white/[0.03]" : "bg-[#141414]/[0.03]"}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors.dot}`} />
                  <span className={`text-[9px] font-mono font-bold ${colors.fg} shrink-0`}>
                    {e.event_type.toUpperCase()}
                  </span>
                  <span className={`text-[9px] font-mono ${fg} truncate`}>
                    {e.service_name}
                    {e.action_taken ? ` · ${e.action_taken}` : ""}
                  </span>
                </div>
                <span className={`text-[9px] font-mono shrink-0 opacity-50 ${fg}`}>
                  {relativeSecsAgo(e.created_at)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
