import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { RefreshCw, Cpu, Cloud, Loader2 } from "lucide-react";
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

interface DiagnoseResponse {
  status?: string;
  provider?: string;
  diagnosis?: string;
}

function entryToPayload(entry: LogEntry): Record<string, unknown> {
  return {
    ts_ns: entry.ts_ns,
    ts: entry.ts,
    level: entry.level,
    service: entry.service,
    node: entry.node,
    trace_id: entry.trace_id,
    message: entry.message,
    raw: entry.raw,
  };
}

/** Up to 5 other logs with same trace_id, or 2 newer + 2 older by list order (newest first). */
function gatherContextEntries(
  list: LogEntry[],
  idx: number,
  entry: LogEntry
): Record<string, unknown>[] {
  const tid = (entry.trace_id || "").trim();
  const noTrace = !tid || tid.toLowerCase() === "no-trace";

  if (!noTrace) {
    const same = list
      .filter((e, i) => i !== idx && (e.trace_id || "").trim() === tid)
      .slice(0, 5);
    return same.map(entryToPayload);
  }

  const newer = list.slice(Math.max(0, idx - 2), idx);
  const older = list.slice(idx + 1, idx + 3);
  return [...newer, ...older].map(entryToPayload);
}

function showDiagnoseActions(level: string): boolean {
  const u = level.toUpperCase();
  return (
    u === "ERROR" || u === "CRITICAL" || u === "UNKNOWN"
  );
}

function renderDiagnosisBody(text: string, isDark: boolean): ReactNode {
  const codeBg = isDark ? "bg-zinc-800/90" : "bg-zinc-200";
  const inlineCode = `${codeBg} rounded px-1 py-0.5 font-mono text-[11px]`;

  const out: ReactNode[] = [];
  let rest = text;
  let key = 0;

  while (rest.length > 0) {
    const fence = rest.indexOf("```");
    if (fence === -1) {
      out.push(...renderInlineOnly(rest, `end-${key}`, inlineCode));
      break;
    }
    if (fence > 0) {
      out.push(...renderInlineOnly(rest.slice(0, fence), `pre-${key}`, inlineCode));
    }
    const close = rest.indexOf("```", fence + 3);
    if (close === -1) {
      out.push(...renderInlineOnly(rest.slice(fence), `broken-${key}`, inlineCode));
      break;
    }
    let code = rest.slice(fence + 3, close);
    const nl = code.indexOf("\n");
    if (nl !== -1 && /^[a-z0-9_-]+$/i.test(code.slice(0, nl).trim())) {
      code = code.slice(nl + 1);
    }
    out.push(
      <pre
        key={`fence-${key}`}
        className={`my-2 overflow-x-auto rounded-lg p-3 font-mono text-xs ${codeBg}`}
      >
        {code.replace(/\n$/, "")}
      </pre>
    );
    rest = rest.slice(close + 3);
    key += 1;
  }

  return <div className="space-y-1 whitespace-pre-wrap text-sm leading-relaxed">{out}</div>;
}

function renderInlineOnly(
  segment: string,
  keyPrefix: string,
  inlineCodeClass: string
): ReactNode[] {
  const parts = segment.split(/`([^`]+)`/);
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <code key={`${keyPrefix}-c-${i}`} className={inlineCodeClass}>
        {part}
      </code>
    ) : (
      <span key={`${keyPrefix}-t-${i}`}>{part}</span>
    )
  );
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

  let q = `${nodePart} | json | line_format "{{.log}}" | json`;

  const allLevels = LEVELS.length === selectedLevels.size;
  if (!allLevels && selectedLevels.size > 0) {
    const pattern = Array.from(selectedLevels)
      .map((l) => l.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|");
    q += ` | level=~"${pattern}"`;
  }

  if (service !== "all") {
    q += ` | service="${service}"`;
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
  const [diagnoseLoading, setDiagnoseLoading] = useState<{
    rowKey: string;
    provider: "local" | "claude";
  } | null>(null);
  const [diagnosePanel, setDiagnosePanel] = useState<{
    rowKey: string;
    provider: "local" | "claude";
    text: string;
    isError: boolean;
  } | null>(null);

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

  const runDiagnose = useCallback(
    async (
      rowKey: string,
      idx: number,
      entry: LogEntry,
      provider: "local" | "claude"
    ) => {
      setDiagnosePanel(null);
      setDiagnoseLoading({ rowKey, provider });
      try {
        const body = {
          entry: entryToPayload(entry),
          context_entries: gatherContextEntries(entries, idx, entry),
          provider,
        };
        const res = await apiFetch("/v1/logs/diagnose", {
          method: "POST",
          body: JSON.stringify(body),
        });
        let data: DiagnoseResponse;
        try {
          data = (await res.json()) as DiagnoseResponse;
        } catch {
          data = { status: "error", diagnosis: "Invalid response" };
        }
        const isError = !res.ok || data.status === "error";
        const text =
          (typeof data.diagnosis === "string" ? data.diagnosis : null) ||
          `HTTP ${res.status}`;
        setDiagnoseLoading(null);
        setDiagnosePanel({ rowKey, provider, text, isError });
      } catch (e) {
        setDiagnoseLoading(null);
        setDiagnosePanel({
          rowKey,
          provider,
          text: String(e),
          isError: true,
        });
      }
    },
    [entries]
  );

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
          <table className="w-full min-w-[1024px] border-collapse text-left text-sm">
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
                <th className={`px-3 py-2.5 text-[10px] font-mono uppercase tracking-wider ${muted}`}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {loading && entries.length === 0 ? (
                <tr>
                  <td colSpan={7} className={`px-4 py-16 text-center ${muted}`}>
                    Loading…
                  </td>
                </tr>
              ) : entries.length === 0 ? (
                <tr>
                  <td colSpan={7} className={`px-4 py-16 text-center ${muted}`}>
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
                  const severe = showDiagnoseActions(entry.level);
                  const load = diagnoseLoading;
                  const loadingHere =
                    load?.rowKey === rowKey;
                  const panelHere = diagnosePanel?.rowKey === rowKey;

                  return (
                    <Fragment key={rowKey}>
                      <tr
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
                        <td className={`max-w-md px-3 py-2 text-xs ${text}`}>
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
                        <td className="whitespace-nowrap px-2 py-2 align-top">
                          {severe ? (
                            loadingHere ? (
                              <div className="flex items-center gap-1 py-0.5">
                                <Loader2 className="h-4 w-4 animate-spin text-zinc-400" />
                                <span className={`text-[10px] ${muted}`}>
                                  {load?.provider === "local"
                                    ? "Local…"
                                    : "Claude…"}
                                </span>
                              </div>
                            ) : (
                              <div className="flex flex-wrap items-center gap-1">
                                <button
                                  type="button"
                                  onClick={() =>
                                    void runDiagnose(rowKey, idx, entry, "local")
                                  }
                                  className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px] font-medium ${border} ${isDark ? "hover:bg-white/5" : "hover:bg-zinc-100"}`}
                                  title="Diagnose with Ollama (local)"
                                >
                                  <Cpu className="h-3 w-3 shrink-0 opacity-70" />
                                  Local
                                </button>
                                <button
                                  type="button"
                                  onClick={() =>
                                    void runDiagnose(rowKey, idx, entry, "claude")
                                  }
                                  className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px] font-medium ${border} ${isDark ? "hover:bg-white/5" : "hover:bg-zinc-100"}`}
                                  title="Diagnose with Claude (gateway)"
                                >
                                  <Cloud className="h-3 w-3 shrink-0 opacity-70" />
                                  Claude
                                </button>
                              </div>
                            )
                          ) : (
                            <span className={muted}>—</span>
                          )}
                        </td>
                      </tr>
                      {panelHere && diagnosePanel && (
                        <tr
                          className={`border-b ${border} ${idx % 2 === 1 ? rowEven : ""}`}
                        >
                          <td colSpan={7} className="px-0 pb-4 pt-0">
                            <div
                              className={`mx-3 overflow-hidden rounded-lg border text-left shadow-lg transition-all ${border} ${
                                diagnosePanel.isError
                                  ? isDark
                                    ? "border-red-500/50 bg-red-950/40"
                                    : "border-red-300 bg-red-50"
                                  : isDark
                                    ? "bg-[#0A0A0A]"
                                    : "bg-zinc-50"
                              }`}
                            >
                              <div
                                className={`flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2 ${border}`}
                              >
                                <span
                                  className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                                    diagnosePanel.provider === "local"
                                      ? isDark
                                        ? "bg-blue-500/25 text-blue-300"
                                        : "bg-blue-100 text-blue-800"
                                      : isDark
                                        ? "bg-violet-500/25 text-violet-300"
                                        : "bg-violet-100 text-violet-800"
                                  }`}
                                >
                                  {diagnosePanel.provider === "local"
                                    ? "Local LLM"
                                    : "Claude"}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => setDiagnosePanel(null)}
                                  className={`rounded px-3 py-1 text-xs font-medium ${isDark ? "hover:bg-white/10" : "hover:bg-zinc-200"}`}
                                >
                                  Close
                                </button>
                              </div>
                              <div
                                className={`max-h-[min(70vh,28rem)] overflow-y-auto px-4 py-3 ${diagnosePanel.isError ? (isDark ? "text-red-200" : "text-red-900") : text}`}
                              >
                                {diagnosePanel.isError ? (
                                  <p className="whitespace-pre-wrap text-sm">
                                    {diagnosePanel.text}
                                  </p>
                                ) : (
                                  renderDiagnosisBody(diagnosePanel.text, isDark)
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
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
