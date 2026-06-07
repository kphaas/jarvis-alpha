import { useState } from "react";
import {
  BarChart3,
  CalendarClock,
  ChevronDown,
  FileCheck2,
  Gavel,
  Radar,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
} from "lucide-react";
import type { PrivacyRemovalControlState } from "../../hooks/usePrivacyRemovalControl";
import type { PrivacyRemovalLane } from "../../types/privacy";
import { StatusLine } from "./PrivacyFields";

const laneIcons: Record<string, typeof Radar> = {
  "P4-A": Radar,
  "P4-B": FileCheck2,
  "P4-C": ShieldCheck,
  "P4-D": BarChart3,
  "P4-E": CalendarClock,
  "P4-F": SearchCheck,
  "P4-G": Gavel,
};

export function PrivacyRemovalControlPanel({
  control,
  border,
  panel,
  muted,
  isDark,
  okClass,
  warnClass,
  errorClass,
}: {
  control: PrivacyRemovalControlState;
  border: string;
  panel: string;
  muted: string;
  isDark: boolean;
  okClass: string;
  warnClass: string;
  errorClass: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const summary = control.summary;
  const counts = summary?.counts;
  const needsInputCount =
    summary?.lanes.filter((lane) => lane.status === "needs_input").length ?? 0;
  const readyLensCount =
    summary?.lenses.filter((lens) => lens.status === "ready").length ?? 0;
  const successIcon = isDark ? "text-emerald-300" : "text-emerald-800";

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <ShieldCheck className={`h-4 w-4 ${successIcon}`} />
            <h2 className="text-base font-semibold">Removal readiness</h2>
          </div>
          <p className={`mt-2 max-w-3xl text-sm leading-6 ${muted}`}>
            P4 Removal Control Plane. Incogni and DeleteMe are the benchmark:
            broad coverage, authorization, recurring checks, status proof,
            custom handling, search deindex, and public-record triage. Alpha
            keeps outbound disabled until a separate go-live approval.
          </p>
        </div>
        <button
          type="button"
          onClick={() => control.refreshSummary()}
          disabled={control.isFetching}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 disabled:opacity-40 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border}`}
        >
          <RefreshCw className={`h-4 w-4 ${control.isFetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      <div className="mt-4 space-y-3">
        {control.error && (
          <StatusLine
            icon="error"
            className={errorClass}
            text="Removal control summary unavailable"
          />
        )}
        {summary && !summary.outbound_enabled && (
          <StatusLine
            icon="ok"
            className={okClass}
            text="Outbound disabled. Operator review remains the active safety gate."
          />
        )}
        {control.isLoading && (
          <div
            className={`h-28 animate-pulse rounded-lg ${isDark ? "bg-white/5" : "bg-[#141414]/5"}`}
          />
        )}
      </div>

      {summary && counts && (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="Targets" value={counts.targets_total} muted={muted} border={border} />
            <Metric
              label="Adapters"
              value={counts.adapter_profiles}
              muted={muted}
              border={border}
            />
            <Metric label="Evidence" value={counts.evidence_items} muted={muted} border={border} />
            <Metric
              label="Due checks"
              value={counts.monitor_runs_due}
              muted={muted}
              border={border}
            />
          </div>

          <div className={`mt-4 rounded-lg border ${border} p-3`}>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold">
                  {readyLensCount} of {summary.lenses.length} readiness lenses ready
                </p>
                <p className={`mt-1 text-sm ${muted}`}>
                  {needsInputCount === 0
                    ? "All lanes have the minimum operating proof."
                    : `${needsInputCount} lane${needsInputCount === 1 ? "" : "s"} need operator input before go-live.`}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setExpanded((current) => !current)}
                aria-expanded={expanded}
                className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 text-sm transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border}`}
              >
                <ChevronDown className={`h-4 w-4 transition ${expanded ? "rotate-180" : ""}`} />
                {expanded ? "Hide operating plan" : "Show operating plan"}
              </button>
            </div>
          </div>

          {expanded && (
            <div className="mt-4 space-y-4">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {summary.lenses.map((lens) => (
                  <div key={lens.code} className={`rounded-lg border ${border} p-3`}>
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-semibold">{lens.label}</p>
                      <span
                        className={`rounded-md border px-2 py-1 text-xs font-medium ${
                          lens.status === "ready" ? okClass : warnClass
                        }`}
                      >
                        {lens.status === "ready" ? "Ready" : "Needs input"}
                      </span>
                    </div>
                    <p className={`mt-2 text-sm leading-5 ${muted}`}>{lens.summary}</p>
                  </div>
                ))}
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                {summary.lanes.map((lane) => (
                  <LaneCard
                    key={lane.code}
                    lane={lane}
                    border={border}
                    muted={muted}
                    okClass={okClass}
                    warnClass={warnClass}
                    isDark={isDark}
                  />
                ))}
              </div>

              <div className={`rounded-lg border ${border} p-4`}>
                <div className="flex items-center gap-2">
                  <BarChart3 className={`h-4 w-4 ${isDark ? "text-sky-300" : "text-sky-800"}`} />
                  <h3 className="text-sm font-semibold">North-star gaps</h3>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  {summary.benchmarks.map((item) => (
                    <div key={`${item.provider}-${item.capability}`} className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`rounded-md border px-2 py-1 text-xs font-medium ${border}`}
                        >
                          {item.provider}
                        </span>
                        <p className="text-sm font-medium">{item.capability}</p>
                      </div>
                      <p className={`text-sm leading-5 ${muted}`}>{item.alpha_gap}</p>
                      <p className="text-sm leading-5 text-emerald-700 dark:text-emerald-300">
                        {item.control}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Metric({
  label,
  value,
  muted,
  border,
}: {
  label: string;
  value: number;
  muted: string;
  border: string;
}) {
  return (
    <div className={`rounded-lg border ${border} px-3 py-3`}>
      <p className={`text-xs font-medium ${muted}`}>{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function LaneCard({
  lane,
  border,
  muted,
  okClass,
  warnClass,
  isDark,
}: {
  lane: PrivacyRemovalLane;
  border: string;
  muted: string;
  okClass: string;
  warnClass: string;
  isDark: boolean;
}) {
  const Icon = laneIcons[lane.code] ?? ShieldCheck;
  return (
    <div className={`rounded-lg border ${border} p-3`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${isDark ? "text-emerald-300" : "text-emerald-800"}`} />
          <div className="min-w-0">
            <p className={`text-xs font-medium ${muted}`}>{lane.code}</p>
            <h3 className="mt-1 text-sm font-semibold">{lane.label}</h3>
          </div>
        </div>
        <span
          className={`shrink-0 rounded-md border px-2 py-1 text-xs font-medium ${
            lane.status === "ready" ? okClass : warnClass
          }`}
        >
          {lane.status === "ready" ? "Ready" : "Needs input"}
        </span>
      </div>
      <p className={`mt-3 text-sm leading-5 ${muted}`}>{lane.current_state}</p>
      <p className="mt-2 text-sm leading-5 text-emerald-700 dark:text-emerald-300">
        {lane.next_step}
      </p>
      <details className={`mt-3 rounded-lg border ${border}`}>
        <summary className={`cursor-pointer px-3 py-2 text-sm font-medium ${muted}`}>
          Evidence key
        </summary>
        <p className={`border-t px-3 py-2 font-mono text-xs ${border}`}>
          {lane.evidence_key}
        </p>
      </details>
    </div>
  );
}
