import {
  BarChart3,
  CalendarClock,
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
  const summary = control.summary;
  const counts = summary?.counts;

  return (
    <section className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-400" />
            <h2 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
              P4 Removal Control Plane
            </h2>
          </div>
          <p className={`mt-2 max-w-3xl text-sm leading-6 ${muted}`}>
            Incogni and DeleteMe are the benchmark: broad coverage,
            authorization, recurring checks, status proof, custom handling, search
            deindex, and public-record triage. Alpha is building that control
            plane with outbound disabled until a separate go-live approval.
          </p>
        </div>
        <button
          type="button"
          onClick={() => control.refreshSummary()}
          disabled={control.isFetching}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition disabled:opacity-40 ${border}`}
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
            className={`h-36 animate-pulse rounded-lg ${isDark ? "bg-white/5" : "bg-[#141414]/5"}`}
          />
        )}
      </div>

      {summary && counts && (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="Targets" value={counts.targets_total} muted={muted} border={border} />
            <Metric label="Adapters" value={counts.adapter_profiles} muted={muted} border={border} />
            <Metric label="Evidence" value={counts.evidence_items} muted={muted} border={border} />
            <Metric label="Due checks" value={counts.monitor_runs_due} muted={muted} border={border} />
          </div>

          <div className="mt-5 grid gap-3 lg:grid-cols-4">
            {summary.lenses.map((lens) => (
              <div key={lens.code} className={`rounded-lg border ${border} p-3`}>
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-semibold">{lens.label}</p>
                  <span
                    className={`rounded-full border px-2 py-1 text-[10px] font-mono uppercase ${
                      lens.status === "ready" ? okClass : warnClass
                    }`}
                  >
                    {lens.status === "ready" ? "ready" : "needs input"}
                  </span>
                </div>
                <p className={`mt-2 text-xs leading-5 ${muted}`}>{lens.summary}</p>
                <ul className={`mt-3 space-y-1 text-[11px] ${muted}`}>
                  {lens.checkpoints.map((checkpoint) => (
                    <li key={checkpoint}>- {checkpoint}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-5 grid gap-3 lg:grid-cols-7">
            {summary.lanes.map((lane) => (
              <LaneCard
                key={lane.code}
                lane={lane}
                border={border}
                muted={muted}
                okClass={okClass}
                warnClass={warnClass}
              />
            ))}
          </div>

          <div className={`mt-5 rounded-lg border ${border} p-4`}>
            <div className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-sky-400" />
              <h3 className={`text-xs font-mono uppercase tracking-widest ${muted}`}>
                North-star gaps
              </h3>
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {summary.benchmarks.map((item) => (
                <div key={`${item.provider}-${item.capability}`} className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
                      {item.provider}
                    </span>
                    <p className="text-sm font-medium">{item.capability}</p>
                  </div>
                  <p className={`text-xs leading-5 ${muted}`}>{item.alpha_gap}</p>
                  <p className="text-xs leading-5 text-emerald-400">{item.control}</p>
                </div>
              ))}
            </div>
          </div>
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
      <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
        {label}
      </p>
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
}: {
  lane: PrivacyRemovalLane;
  border: string;
  muted: string;
  okClass: string;
  warnClass: string;
}) {
  const Icon = laneIcons[lane.code] ?? ShieldCheck;
  return (
    <div className={`rounded-lg border ${border} p-3 lg:min-h-[220px]`}>
      <div className="flex items-start justify-between gap-2">
        <Icon className="mt-0.5 h-4 w-4 text-emerald-400" />
        <span
          className={`rounded-full border px-2 py-1 text-[10px] font-mono uppercase ${
            lane.status === "ready" ? okClass : warnClass
          }`}
        >
          {lane.status === "ready" ? "ready" : "input"}
        </span>
      </div>
      <p className={`mt-3 text-[10px] font-mono uppercase tracking-widest ${muted}`}>
        {lane.code}
      </p>
      <h3 className="mt-1 text-sm font-semibold">{lane.label}</h3>
      <p className={`mt-2 text-xs leading-5 ${muted}`}>{lane.current_state}</p>
      <p className="mt-2 text-xs leading-5 text-emerald-400">{lane.next_step}</p>
      <div className={`mt-3 rounded-md border ${border} px-2 py-2`}>
        <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>
          Proof key
        </p>
        <p className="mt-1 break-all text-[11px]">{lane.evidence_key}</p>
      </div>
    </div>
  );
}
