import {
  NODES,
  LEVELS,
  SERVICES,
  SINCE_OPTIONS,
  type Since,
} from "./utils";

interface FilterBarProps {
  isDark: boolean;
  since: string;
  setSince: (v: string) => void;
  service: string;
  setService: (v: string) => void;
  textSearch: string;
  setTextSearch: (v: string) => void;
  autoRefresh: boolean;
  setAutoRefresh: (v: boolean) => void;
  selectedNodes: Set<string>;
  toggleNode: (n: string) => void;
  selectedLevels: Set<string>;
  toggleLevel: (l: string) => void;
  filterSummary: string;
}

export function FilterBar({
  isDark,
  since,
  setSince,
  service,
  setService,
  textSearch,
  setTextSearch,
  autoRefresh,
  setAutoRefresh,
  selectedNodes,
  toggleNode,
  selectedLevels,
  toggleLevel,
  filterSummary,
}: FilterBarProps) {
  const border = isDark ? "border-white/10" : "border-[#141414]/15";
  const panel = isDark ? "bg-[#0F0F0F]" : "bg-white";
  const muted = isDark ? "text-zinc-500" : "text-zinc-600";
  const text = isDark ? "text-[#E4E3E0]" : "text-[#141414]";
  const inputBg = isDark ? "bg-[#0A0A0A]" : "bg-zinc-50";

  return (
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
            placeholder="e.g. error text or trace id"
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

      <p className={`text-[10px] leading-relaxed ${muted}`}>
        Active filters: <span className={`font-medium ${text}`}>{filterSummary}</span>
      </p>
    </div>
  );
}
