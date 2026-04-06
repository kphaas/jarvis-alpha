import type { ReactNode } from 'react'
import type { ErrorLogEntry } from '../../types/errors'

export function isPatternAnalyzeTimeout(e: unknown): boolean {
  if (e instanceof Error && (e.name === "AbortError" || e.name === "TimeoutError")) {
    return true;
  }
  if (typeof DOMException !== "undefined" && e instanceof DOMException) {
    return e.name === "TimeoutError" || e.name === "AbortError";
  }
  return false;
}

export function patternSeverityBarClass(severity: string, isDark: boolean): string {
  const s = severity.toUpperCase();
  if (s === "CRITICAL") return isDark ? "bg-red-500" : "bg-red-600";
  if (s === "HIGH") return isDark ? "bg-orange-500" : "bg-orange-600";
  if (s === "MEDIUM") return isDark ? "bg-amber-500" : "bg-amber-600";
  if (s === "LOW") return isDark ? "bg-blue-500" : "bg-blue-600";
  return isDark ? "bg-zinc-500" : "bg-zinc-400";
}

export function entryToPayload(entry: ErrorLogEntry): Record<string, unknown> {
  return {
    ts_ns: entry.ts_ns, ts: entry.ts, level: entry.level,
    service: entry.service, node: entry.node, trace_id: entry.trace_id,
    message: entry.message, raw: entry.raw,
  };
}

export function gatherContextEntries(
  list: ErrorLogEntry[], idx: number, entry: ErrorLogEntry
): Record<string, unknown>[] {
  const tid = (entry.trace_id || "").trim();
  const noTrace = !tid || tid.toLowerCase() === "no-trace";
  if (!noTrace) {
    const same = list.filter((e, i) => i !== idx && (e.trace_id || "").trim() === tid).slice(0, 5);
    return same.map(entryToPayload);
  }
  const newer = list.slice(Math.max(0, idx - 2), idx);
  const older = list.slice(idx + 1, idx + 3);
  return [...newer, ...older].map(entryToPayload);
}

export function showDiagnoseActions(level: string): boolean {
  const u = level.toUpperCase();
  return u === "ERROR" || u === "CRITICAL" || u === "UNKNOWN";
}

export function renderDiagnosisBody(text: string, isDark: boolean): ReactNode {
  const codeBg = isDark ? "bg-zinc-800/90" : "bg-zinc-200";
  const inlineCode = `${codeBg} rounded px-1 py-0.5 font-mono text-[11px]`;
  const out: ReactNode[] = [];
  let rest = text;
  let key = 0;
  while (rest.length > 0) {
    const fence = rest.indexOf("```");
    if (fence === -1) { out.push(...renderInlineOnly(rest, `end-${key}`, inlineCode)); break; }
    if (fence > 0) { out.push(...renderInlineOnly(rest.slice(0, fence), `pre-${key}`, inlineCode)); }
    const close = rest.indexOf("```", fence + 3);
    if (close === -1) { out.push(...renderInlineOnly(rest.slice(fence), `broken-${key}`, inlineCode)); break; }
    let code = rest.slice(fence + 3, close);
    const nl = code.indexOf("\n");
    if (nl !== -1 && /^[a-z0-9_-]+$/i.test(code.slice(0, nl).trim())) { code = code.slice(nl + 1); }
    out.push(
      <pre key={`fence-${key}`} className={`my-2 overflow-x-auto rounded-lg p-3 font-mono text-xs ${codeBg}`}>
        {code.replace(/\n$/, "")}
      </pre>
    );
    rest = rest.slice(close + 3);
    key += 1;
  }
  return <div className="space-y-1 whitespace-pre-wrap text-sm leading-relaxed">{out}</div>;
}

function renderInlineOnly(segment: string, keyPrefix: string, inlineCodeClass: string): ReactNode[] {
  const parts = segment.split(/`([^`]+)`/);
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <code key={`${keyPrefix}-c-${i}`} className={inlineCodeClass}>{part}</code>
    ) : (
      <span key={`${keyPrefix}-t-${i}`}>{part}</span>
    )
  );
}

export function describeActiveFilters(
  selectedNodes: Set<string>, selectedLevels: Set<string>,
  svc: string, textSearch: string
): string {
  const parts: string[] = [];
  if (selectedNodes.size < 4) parts.push(`Nodes: ${[...selectedNodes].join(", ")}`);
  if (selectedLevels.size < 4) parts.push(`Levels: ${[...selectedLevels].join(", ")}`);
  if (svc !== "all") parts.push(`Service: ${svc}`);
  if (textSearch) parts.push(`Search: "${textSearch}"`);
  return parts.join(" · ");
}

export function parseEntryTime(entry: ErrorLogEntry): Date | null {
  if (entry.ts) {
    const d = new Date(entry.ts);
    if (!Number.isNaN(d.getTime())) return d;
  }
  const ns = parseInt(entry.ts_ns, 10);
  if (!Number.isNaN(ns)) return new Date(ns / 1e6);
  return null;
}

export function formatTimestamp(d: Date | null, showDate: boolean): string {
  if (!d) return "—";
  const time = d.toLocaleTimeString(undefined, {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
  if (!showDate) return time;
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${time}`;
}

export function levelBadgeClass(level: string, isDark: boolean): string {
  const lv = level.toUpperCase();
  if (lv === "CRITICAL") {
    return `animate-pulse text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${isDark ? "border-red-500/50 bg-red-500/30 text-red-300" : "border-red-400 bg-red-100 text-red-900"}`;
  }
  if (lv === "ERROR") {
    return `text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${isDark ? "border-rose-500/40 bg-rose-500/20 text-rose-300" : "border-rose-400 bg-rose-50 text-rose-800"}`;
  }
  if (lv === "WARNING") {
    return `text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${isDark ? "border-amber-500/40 bg-amber-500/20 text-amber-300" : "border-amber-400 bg-amber-50 text-amber-800"}`;
  }
  return `text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${isDark ? "border-zinc-600 bg-zinc-700/40 text-zinc-300" : "border-zinc-300 bg-zinc-100 text-zinc-600"}`;
}

export const NODES = ["brain", "gateway", "endpoint", "sandbox"] as const;
export const LEVELS = ["INFO", "WARNING", "ERROR", "CRITICAL"] as const;
export const SERVICES = [
  "all", "alpha_brain", "alpha_buddy", "alpha_executor",
  "alpha_watchdog", "alpha_dispatch", "alpha_memory", "unknown",
] as const;
export const SINCE_OPTIONS = ["15m", "1h", "6h", "24h", "7d"] as const;
export type Since = (typeof SINCE_OPTIONS)[number];
export const MSG_PREVIEW = 160;
export const PATTERN_FETCH_MS = 90_000;
