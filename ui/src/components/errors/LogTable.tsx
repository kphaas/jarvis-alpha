import { Fragment } from "react";
import { Cpu, Cloud, Loader2 } from "lucide-react";
import type { ErrorLogEntry as LogEntry } from "../../types/errors";
import {
  parseEntryTime,
  formatTimestamp,
  levelBadgeClass,
  showDiagnoseActions,
  renderDiagnosisBody,
  MSG_PREVIEW,
} from "./utils";

interface LogTableProps {
  isDark: boolean;
  entries: LogEntry[];
  isLoading: boolean;
  expandedKey: string | null;
  setExpandedKey: (key: string | null) => void;
  setTextSearch: (v: string) => void;
  diagnoseLoading: { rowKey: string; provider: "local" | "claude" } | null;
  diagnosePanel: { rowKey: string; provider: "local" | "claude"; text: string; isError: boolean } | null;
  onDiagnose: (rowKey: string, idx: number, entry: LogEntry, provider: "local" | "claude") => void;
  onCloseDiagnose: () => void;
  showDate: boolean;
}

export function LogTable({
  isDark,
  entries,
  isLoading,
  expandedKey,
  setExpandedKey,
  setTextSearch,
  diagnoseLoading,
  diagnosePanel,
  onDiagnose,
  onCloseDiagnose,
  showDate,
}: LogTableProps) {
  const border = isDark ? "border-white/10" : "border-[#141414]/15";
  const panel = isDark ? "bg-[#0F0F0F]" : "bg-white";
  const muted = isDark ? "text-zinc-500" : "text-zinc-600";
  const text = isDark ? "text-[#E4E3E0]" : "text-[#141414]";
  const rowEven = isDark ? "bg-white/[0.03]" : "bg-zinc-50/80";

  return (
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
            {isLoading && entries.length === 0 ? (
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
                                  void onDiagnose(rowKey, idx, entry, "local")
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
                                  void onDiagnose(rowKey, idx, entry, "claude")
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
                                onClick={onCloseDiagnose}
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
  );
}
