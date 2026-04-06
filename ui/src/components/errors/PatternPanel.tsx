import { Loader2 } from "lucide-react";
import type { PatternPanelState } from "../../types/errors";
import {
  patternSeverityBarClass,
  renderDiagnosisBody,
} from "./utils";

interface PatternPanelProps {
  isDark: boolean;
  patternPanel: PatternPanelState;
  onClose: () => void;
}

export function PatternPanel({ isDark, patternPanel, onClose }: PatternPanelProps) {
  if (!patternPanel) return null;

  const border = isDark ? "border-white/10" : "border-[#141414]/15";
  const panel = isDark ? "bg-[#0F0F0F]" : "bg-white";
  const muted = isDark ? "text-zinc-500" : "text-zinc-600";
  const text = isDark ? "text-[#E4E3E0]" : "text-[#141414]";

  return (
    <div
      className={`mb-4 overflow-hidden rounded-xl border ${border} ${panel}`}
    >
      <div
        className={`flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3 ${border}`}
      >
        <div>
          <h2 className={`text-sm font-semibold ${text}`}>Pattern Analysis</h2>
          <p className={`text-[10px] font-mono ${muted}`}>
            {patternPanel.phase === "loading"
              ? `Started ${patternPanel.startedAt.toLocaleString()}`
              : patternPanel.phase === "done" || patternPanel.phase === "error"
                ? patternPanel.at.toLocaleString()
                : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className={`rounded-lg px-3 py-1.5 text-xs font-medium ${isDark ? "hover:bg-white/10" : "hover:bg-zinc-100"}`}
        >
          Close
        </button>
      </div>

      <div className="space-y-4 p-4">
        {patternPanel.phase === "loading" && (
          <div className={`flex flex-col items-center gap-3 py-8 ${muted}`}>
            <Loader2 className="h-8 w-8 animate-spin text-emerald-500" />
            <p className={`text-center text-sm ${text}`}>
              Analyzing patterns…
            </p>
            <p className="max-w-md text-center text-xs">
              Ollama inference can take 30–60 seconds. This request times out after 90s.
            </p>
          </div>
        )}

        {patternPanel.phase === "error" && (
          <div
            className={`rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm ${isDark ? "text-red-200" : "text-red-900"}`}
          >
            {patternPanel.message}
          </div>
        )}

        {patternPanel.phase === "done" && (() => {
          const analysis = patternPanel.data.analysis;
          const rows = analysis?.patterns ?? [];
          const summary = analysis?.summary ?? "";
          const hasStructured = rows.length > 0;

          return (
            <>
              {hasStructured ? (
                <>
                  {summary && (
                    <p className={`text-sm leading-relaxed ${text}`}>{summary}</p>
                  )}
                  {patternPanel.data.raw_log_count != null && (
                    <p className={`text-[11px] ${muted}`}>
                      {patternPanel.data.raw_log_count} log lines ·{" "}
                      {patternPanel.data.pattern_count ?? rows.length} pattern groups
                      (top 10 sent to model)
                    </p>
                  )}
                  <div className="space-y-3">
                    {rows.map((p, i) => (
                      <div
                        key={`${p.title ?? "p"}-${i}`}
                        className={`flex overflow-hidden rounded-lg border ${border} ${isDark ? "bg-[#0A0A0A]" : "bg-zinc-50"}`}
                      >
                        <div
                          className={`w-1 shrink-0 ${patternSeverityBarClass(p.severity ?? "", isDark)}`}
                          aria-hidden
                        />
                        <div className="min-w-0 flex-1 p-4">
                          <div className="mb-2 flex flex-wrap items-center gap-2">
                            <span className={`font-semibold ${text}`}>
                              {p.title ?? "Pattern"}
                            </span>
                            {p.count != null && (
                              <span
                                className={`rounded-full border px-2 py-0.5 text-[10px] font-mono ${border} ${muted}`}
                              >
                                ×{p.count}
                              </span>
                            )}
                            {(p.nodes ?? []).map((n) => (
                              <span
                                key={n}
                                className={`rounded border px-2 py-0.5 text-[10px] font-mono ${border} ${muted}`}
                              >
                                {n}
                              </span>
                            ))}
                          </div>
                          {p.root_cause && (
                            <p className={`mb-3 text-sm leading-relaxed ${muted}`}>
                              {p.root_cause}
                            </p>
                          )}
                          {p.fix && (
                            <pre
                              className={`whitespace-pre-wrap rounded-lg p-3 font-mono text-xs leading-relaxed ${isDark ? "bg-zinc-900/80 text-zinc-200" : "bg-zinc-200/80 text-zinc-900"}`}
                            >
                              {p.fix}
                            </pre>
                          )}
                          {p.related_to != null && p.related_to !== "" && (
                            <p className={`mt-2 text-xs ${muted}`}>
                              Related to:{" "}
                              <span className={text}>{String(p.related_to)}</span>
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              ) : summary ? (
                <div className={`text-sm ${text}`}>
                  {renderDiagnosisBody(summary, isDark)}
                </div>
              ) : null}
            </>
          );
        })()}
      </div>
    </div>
  );
}
