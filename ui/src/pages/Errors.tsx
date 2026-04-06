import { useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Loader2, Sparkles } from "lucide-react";
import { apiFetch } from "../lib/apiFetch";
import { useLogs } from "../hooks/useLogs";
import type {
  ErrorLogEntry as LogEntry,
  DiagnoseResponse,
  AnalyzePatternsApiResponse,
  PatternPanelState,
} from "../types/errors";
import {
  isPatternAnalyzeTimeout,
  entryToPayload,
  gatherContextEntries,
  describeActiveFilters,
  NODES,
  LEVELS,
  SERVICES,
  PATTERN_FETCH_MS,
  type Since,
  FilterBar,
  PatternPanel,
  LogTable,
} from "../components/errors";

export default function Errors({ theme }: { theme: "dark" | "light" }) {
  const isDark = theme === "dark";
  const queryClient = useQueryClient();
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
  const [patternPanel, setPatternPanel] = useState<PatternPanelState>(null);

  const showDate = since === "7d";
  const patternLoading = patternPanel?.phase === "loading";
  const { entries, count, isLoading, error, refetch } = useLogs(
    {
      since,
      selectedNodes,
      selectedLevels,
      service,
      textSearch,
    },
    autoRefresh
  );

  const filterSummary = useMemo(
    () =>
      describeActiveFilters(selectedNodes, selectedLevels, service, textSearch),
    [selectedNodes, selectedLevels, service, textSearch]
  );

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

  const runAnalyzePatterns = useCallback(async () => {
    setPatternPanel({ phase: "loading", startedAt: new Date() });
    try {
      const params = new URLSearchParams();
      params.set("since", since);
      params.set("nodes", Array.from(selectedNodes).join(","));
      const res = await apiFetch(`/v1/logs/analyze-patterns?${params.toString()}`, {
        signal: AbortSignal.timeout(PATTERN_FETCH_MS),
      });
      let data: AnalyzePatternsApiResponse;
      try {
        data = (await res.json()) as AnalyzePatternsApiResponse;
      } catch {
        data = { status: "error", error: "Invalid response" };
      }
      if (!res.ok || data.status === "error") {
        setPatternPanel({
          phase: "error",
          at: new Date(),
          message: data.error || `HTTP ${res.status}`,
        });
        return;
      }
      setPatternPanel({ phase: "done", at: new Date(), data });
      void queryClient.invalidateQueries({ queryKey: ["logs", "query"] });
    } catch (e) {
      const message = isPatternAnalyzeTimeout(e)
        ? "Analysis timed out — try a shorter time range"
        : String(e);
      setPatternPanel({ phase: "error", at: new Date(), message });
    }
  }, [since, selectedNodes, queryClient]);

  const border = isDark ? "border-white/10" : "border-[#141414]/15";
  const panel = isDark ? "bg-[#0F0F0F]" : "bg-white";
  const muted = isDark ? "text-zinc-500" : "text-zinc-600";

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
            {isLoading ? "…" : count} entries
          </span>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isLoading}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${border} ${panel} hover:opacity-90 disabled:opacity-40`}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => void runAnalyzePatterns()}
            disabled={patternLoading}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold transition-colors disabled:opacity-40 ${
              isDark
                ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25"
                : "border-emerald-600/50 bg-emerald-50 text-emerald-900 hover:bg-emerald-100"
            }`}
          >
            {patternLoading ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Analyzing…
              </>
            ) : (
              <>
                <Sparkles className="h-3.5 w-3.5" />
                Analyze Patterns
              </>
            )}
          </button>
        </div>
      </div>

      <FilterBar
        isDark={isDark}
        since={since}
        setSince={(v) => setSince(v as Since)}
        service={service}
        setService={(v) => setService(v as (typeof SERVICES)[number])}
        textSearch={textSearch}
        setTextSearch={setTextSearch}
        autoRefresh={autoRefresh}
        setAutoRefresh={setAutoRefresh}
        selectedNodes={selectedNodes}
        toggleNode={toggleNode}
        selectedLevels={selectedLevels}
        toggleLevel={toggleLevel}
        filterSummary={filterSummary}
      />

      {error && (
        <div
          className={`mb-4 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-400`}
        >
          {error}
        </div>
      )}

      {patternPanel && (
        <PatternPanel
          isDark={isDark}
          patternPanel={patternPanel}
          onClose={() => setPatternPanel(null)}
        />
      )}

      <LogTable
        isDark={isDark}
        entries={entries}
        isLoading={isLoading}
        expandedKey={expandedKey}
        setExpandedKey={setExpandedKey}
        setTextSearch={setTextSearch}
        diagnoseLoading={diagnoseLoading}
        diagnosePanel={diagnosePanel}
        onDiagnose={runDiagnose}
        onCloseDiagnose={() => setDiagnosePanel(null)}
        showDate={showDate}
      />
    </div>
  );
}
