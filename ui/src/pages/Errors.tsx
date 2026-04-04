import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { apiFetch } from "../lib/apiFetch";

const NODES = ["brain", "gateway", "endpoint", "sandbox"] as const;
const LEVELS = ["INFO", "WARNING", "ERROR", "CRITICAL"] as const;
const SERVICES = [
  "all",
  "alpha_brain",
  "alpha_buddy",
  "alpha_executor",
  "alpha_watchdog",
  "alpha_dispatch",
  "alpha_memory",
  "unknown",
] as const;

const SINCE_OPTIONS = ["15m", "1h", "6h", "24h", "7d"] as const;

type Since = (typeof SINCE_OPTIONS)[number];

interface LogEntry {
  ts_ns: string;
  node: string;
  raw: string;
  ts: string;
  level: string;
  service: string;
  trace_id: string;
  message: string;
}

interface QueryResponse {
  status: string;
  count?: number;
  entries?: LogEntry[];
  error?: string;
}

function buildLogQL(
  selectedNodes: Set<string>,
  selectedLevels: Set<string>,
  service: (typeof SERVICES)[number],
  textSearch: string
): string {
  const allNodes = NODES.length === selectedNodes.size;
  const nodePart = allNodes
    ? '{node=~".+"}'
    : `{node=~"${Array.from(selectedNodes).join("|")}"}`;

  let q = nodePart;

  const allLevels = LEVELS.length === selectedLevels.size;
  if (!allLevels && selectedLevels.size > 0) {
    const pattern = Array.from(selectedLevels)
      .map((l) => l.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|");
    q += ` |~ "${pattern}"`;
  }

  if (service !== "all") {
    q += ` |= "\\"service\\": \\"${service}\\""`;
  }

  const t = textSearch.trim();
  if (t) {
    const escaped = t.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    q += ` |= "${escaped}"`;
  }

  return q;
}

function parseEntryTime(entry: LogEntry): Date | null {
  if (entry.ts) {
    const d = new Date(entry.ts);
    if (!Number.isNaN(d.getTime())) return d;
  }
  const ns = Number(entry.ts_ns);
  if (!Number.isNaN(ns)) return new Date(ns / 1e6);
  return null;
}

function formatTimestamp(d: Date | null, showDate: boolean): string {
  if (!d) return "—";
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  const h = pad(d.getHours());
  const m = pad(d.getMinutes());
  const s = pad(d.getSeconds());
  const ms = pad(d.getMilliseconds(), 3);
  const time = `${h}:${m}:${s}.${ms}`;
  if (!showDate) return time;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`;
}

function levelBadgeClass(level: string, isDark: boolean): string {
  const u = level.toUpperCase();
  const base = "inline-flex items-center rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide";
  if (u === "INFO") {
    return `${base} ${isDark ? "bg-blue-500/20 text-blue-400" : "bg-blue-100 text-blue-800"}`;
  }
  if (u === "WARNING") {
    return `${base} ${isDark ? "bg-amber-500/20 text-amber-400" : "bg-amber-100 text-amber-800"}`;
  }
  if (u === "ERROR") {
    return `${base} ${isDark ? "bg-red-500/20 text-red-400" : "bg-red-100 text-red-800"}`;
  }
  if (u === "CRITICAL") {
    return `${base} font-bold ${isDark ? "bg-red-600/30 text-red-300" : "bg-red-200 text-red-900"}`;
  }
  return `${base} ${isDark ? "bg-zinc-500/20 text-zinc-400" : "bg-zinc-200 text-zinc-700"}`;
}

const MSG_PREVIEW = 160;

export default function Errors({ theme }: { theme: "dark" | "light" }) {
  const isDark = theme === "dark";
  const [since, setSince] = useState<Since>("1h");
  const [selectedNodes, setSelectedNodes] = useState<Set<string>>(
    () => new Set(NODES)
  );
  const [selectedLevels, setSelectedLevels] = useState<Set<string>>(
    () => new Set(LEVELS)
  );
  const [service, setService] = useState<(typeof SERVICES)[number]>("all");
  const [textSearch, setTextSearch] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [count, setCount] = useState(0);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  const showDate = since === "7d";

  const logql = useMemo(
    () => buildLogQL(selectedNodes, selectedLevels, service, textSearch),
    [selectedNodes, selectedLevels, service, textSearch]
  );

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const params = new URLSearchParams();
      params.set("query", logql);
      params.set("limit", "500");
      params.set("since", since);
      const res = await apiFetch(`/v1/logs/query?${params.toString()}`);
      const data = (await res.json()) as QueryResponse;
      if (!res.ok) {
        setFetchError(data.error || `HTTP ${res.status}`);
        setEntries([]);
        setCount(0);
        return;
      }
      if (data.status === "error") {
        setFetchError(data.error || "Query failed");
        setEntries([]);
        setCount(0);
        return;
      }
      setEntries(data.entries ?? []);
      setCount(data.count ?? 0);
    } catch (e) {
      setFetchError(String(e));
      setEntries([]);
      setCount(0);
    } finally {
      setLoading(false);
    }
  }, [logql, since]);

  useEffect(() => {
    void fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => void fetchLogs(), 30_000);
    return () => clearInterval(id);
  }, [autoRefresh, fetchLogs]);

  const toggleNode = (n: string) => {
    setSelectedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(n)) next.delete(n);
      else next.add(n);
      if (next.size === 0) return new Set(NODES);
      return next;
    });
  };

  const toggleLevel = (l: string) => {
    setSelectedLevels((prev) => {
      const next = new Set(prev);
      if (next.has(l)) next.delete(l);
      else next.add(l);
      if (next.size === 0) return new Set(LEVELS);
      return next;
    });
  };

  const border = isDark ? "border-white/10" : "border-[#141414]/15";
  const panel = isDark ? "bg-[#0F0F0F]" : "bg-white";
  const muted = isDark ? "text-zinc-500" : "text-zinc-600";
  const text = isDark ? "text-[#E4E3E0]" : "text-[#141414]";
  const inputBg = isDark ? "bg-[#0A0A0A]" : "bg-zinc-50";
  const rowEven = isDark ? "bg-white/[0.03]" : "bg-zinc-50/80";

  return (
    <div className={`min-h-full ${isDark ? "text-[#E4E3E0]" : "text-[#141414]"}`}>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-serif text-2xl italic">Errors &amp; Logs</h1>
          <p className={`mt-1 text-xs font-mono ${muted}`}>Loki · structured JSON</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`rounded-full border px-3 py-1 text-xs font-mono ${border} ${panel}`}
          >
            {loading ? "…" : count} entries
          </span>
          <button
            type="button"
            onClick={() => void fetchLogs()}
            disabled={loading}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${border} ${panel} hover:opacity-90 disabled:opacity-40`}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Filters */}
      <div
        className={`mb-4 flex flex-col gap-4 rounded-xl border p-4 ${border} ${panel}`}
      >
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1">
            <span className={`text-[10px] font-mono uppercase tracking-wider ${muted}`}>
              Time range
            </span>
            <select
              value={since}
              onChange={(e) => setSince(e.target.value as Since)}
              className={`rounded-lg border px-3 py-2 text-sm ${border} ${inputBg} ${text}`}
            >
              {SINCE_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className={`text-[10px] font-mono uppercase tracking-wider ${muted}`}>
              Service
            </span>
            <select
              value={service}
              onChange={(e) =>
                setService(e.target.value as (typeof SERVICES)[number])
              }
              className={`rounded-lg border px-3 py-2 text-sm ${border} ${inputBg} ${text}`}
            >
              {SERVICES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>

          <label className="flex min-w-[200px] flex-1 flex-col gap-1">
            <span className={`text-[10px] font-mono uppercase tracking-wider ${muted}`}>
              Text search
            </span>
            <input
              type="search"
              value={textSearch}
              onChange={(e) => setTextSearch(e.target.value)}
              placeholder='e.g. error text or trace id'
              className={`rounded-lg border px-3 py-2 text-sm ${border} ${inputBg} ${text} placeholder:opacity-40`}
            />
          </label>

          <label className="flex cursor-pointer items-center gap-2 self-end pb-2">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-zinc-500"
            />
            <span className={`text-xs ${text}`}>Auto-refresh (30s)</span>
          </label>
        </div>

        <div>
          <span className={`mb-2 block text-[10px] font-mono uppercase tracking-wider ${muted}`}>
            Node
          </span>
          <div className="flex flex-wrap gap-2">
            {NODES.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => toggleNode(n)}
                className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${border} ${
                  selectedNodes.has(n)
                    ? isDark
                      ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300"
                      : "border-emerald-600 bg-emerald-50 text-emerald-900"
                    : `${inputBg} opacity-50`
                }`}
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        <div>
          <span className={`mb-2 block text-[10px] font-mono uppercase tracking-wider ${muted}`}>
            Level
          </span>
          <div className="flex flex-wrap gap-2">
            {LEVELS.map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => toggleLevel(l)}
                className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${border} ${
                  selectedLevels.has(l)
                    ? isDark
                      ? "border-sky-500/40 bg-sky-500/10 text-sky-200"
                      : "border-sky-500 bg-sky-50 text-sky-900"
                    : `${inputBg} opacity-50`
                }`}
              >
                {l}
              </button>
            ))}
          </div>
        </div>

        <p className={`break-all font-mono text-[10px] ${muted}`}>
          LogQL: <span className={text}>{logql}</span>
        </p>
      </div>

      {fetchError && (
        <div
          className={`mb-4 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-400`}
        >
          {fetchError}
        </div>
      )}

      {/* Table */}
      <div className={`overflow-hidden rounded-xl border ${border} ${panel}`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] border-collapse text-left text-sm">
            <thead>
              <tr className={`border-b ${border} ${isDark ? "bg-black/20" : "bg-zinc-100"}`}>
                <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>
                  Timestamp
                </th>
                <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>
                  Level
                </th>
                <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>
                  Service
                </th>
                <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>
                  Node
                </th>
                <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>
                  Trace ID
                </th>
                <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>
                  Message
                </th>
              </tr>
            </thead>
            <tbody>
              {loading && entries.length === 0 ? (
                <tr>
                  <td colSpan={6} className={`px-4 py-16 text-center ${muted}`}>
                    Loading…
                  </td>
                </tr>
              ) : entries.length === 0 ? (
                <tr>
                  <td colSpan={6} className={`px-4 py-16 text-center ${muted}`}>
                    No logs found
                  </td>
                </tr>
              ) : (
                entries.map((entry, idx) => {
                  const rowKey = `${entry.ts_ns}-${idx}`;
                  const d = parseEntryTime(entry);
                  const msg = entry.message || entry.raw;
                  const expanded = expandedKey === rowKey;
                  const short =
                    msg.length > MSG_PREVIEW && !expanded
                      ? `${msg.slice(0, MSG_PREVIEW)}…`
                      : msg;

                  return (
                    <tr
                      key={rowKey}
                      className={`border-b ${border} ${idx % 2 === 1 ? rowEven : ""}`}
                    >
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">
                        {formatTimestamp(d, showDate)}
                      </td>
                      <td className="px-3 py-2">
                        <span className={levelBadgeClass(entry.level, isDark)}>
                          {entry.level}
                        </span>
                      </td>
                      <td className={`px-3 py-2 font-mono text-xs ${text}`}>
                        {entry.service}
                      </td>
                      <td className={`px-3 py-2 font-mono text-xs ${muted}`}>
                        {entry.node}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {entry.trace_id ? (
                          <button
                            type="button"
                            onClick={() => setTextSearch(entry.trace_id)}
                            className={
                              isDark
                                ? "text-sky-400 underline decoration-sky-500/50 hover:text-sky-300"
                                : "text-sky-700 underline hover:text-sky-900"
                            }
                          >
                            {entry.trace_id}
                          </button>
                        ) : (
                          <span className={muted}>—</span>
                        )}
                      </td>
                      <td className={`max-w-xl px-3 py-2 text-xs ${text}`}>
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedKey(expanded ? null : rowKey)
                          }
                          className="w-full text-left"
                        >
                          <span className="break-words">{short}</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
