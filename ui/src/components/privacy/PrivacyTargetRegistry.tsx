import { useMemo, useState } from "react";
import { Database, RefreshCw, Search, X } from "lucide-react";
import type { PrivacyTargetCategory } from "../../types/privacy";
import { TARGET_CATEGORIES, TARGET_METHOD_LABEL } from "../../types/privacy";
import type { PrivacyTargetsState } from "../../hooks/usePrivacyTargets";
import { StatusLine } from "./PrivacyFields";
import { PrivacyTargetCard } from "./PrivacyTargetCard";

type CategoryFilter = "all" | PrivacyTargetCategory;

const COLLAPSED_TARGET_LIMIT = 8;

export function PrivacyTargetRegistry({
  targets,
  subjectId,
  border,
  panel,
  muted,
  isDark,
  okClass,
  warnClass,
  errorClass,
}: {
  targets: PrivacyTargetsState;
  subjectId: string | null;
  border: string;
  panel: string;
  muted: string;
  isDark: boolean;
  okClass: string;
  warnClass: string;
  errorClass: string;
}) {
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredTargets = useMemo(
    () =>
      targets.targets.filter((target) => {
        const matchesCategory = category === "all" || target.category === category;
        const searchable = [
          target.name,
          target.id,
          target.jurisdiction,
          target.category.replace("_", " "),
          TARGET_METHOD_LABEL[target.opt_out_method],
        ]
          .join(" ")
          .toLowerCase();
        return matchesCategory && (!normalizedQuery || searchable.includes(normalizedQuery));
      }),
    [category, normalizedQuery, targets.targets],
  );
  const visibleTargets = showAll
    ? filteredTargets
    : filteredTargets.slice(0, COLLAPSED_TARGET_LIMIT);
  const hiddenTargetCount = Math.max(0, filteredTargets.length - visibleTargets.length);
  const statusText = subjectId
    ? `${targets.selectedCount} selected, ${filteredTargets.length} matches`
    : `Create a subject first. ${filteredTargets.length} matching targets are ready.`;

  function chooseCategory(nextCategory: CategoryFilter) {
    setCategory(nextCategory);
    setShowAll(false);
  }

  return (
    <section id="privacy-target-registry" className={`rounded-xl border ${border} ${panel} p-5`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border ${border}`}>
            <Database className={`h-5 w-5 ${isDark ? "text-sky-300" : "text-sky-800"}`} />
          </div>
          <div>
            <h2 className="text-base font-semibold">Target registry</h2>
            <p className={`mt-1 max-w-2xl text-sm leading-6 ${muted}`}>
              Select one or more brokers, public-record sources, social sites,
              or breach records to include in the next packet.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {targets.selectedCount > 0 && (
            <button
              type="button"
              onClick={targets.clearSelection}
              className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border}`}
              aria-label="Clear selected targets"
            >
              <X className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            onClick={() => targets.refreshTargets()}
            disabled={targets.refreshLoading}
            className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-3 text-sm transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 disabled:opacity-40 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border}`}
          >
            <RefreshCw
              className={`h-4 w-4 ${targets.refreshLoading ? "animate-spin" : ""}`}
            />
            Refresh
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
        <label className="relative block">
          <span className="sr-only">Search targets</span>
          <Search className={`pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${muted}`} />
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setShowAll(false);
            }}
            placeholder="Search targets"
            className={`min-h-11 w-full rounded-lg border pl-10 pr-3 text-sm outline-none transition focus:border-emerald-600 focus-visible:ring-2 focus-visible:ring-emerald-700/25 dark:focus:border-emerald-400 dark:focus-visible:ring-emerald-300/25 ${
              isDark
                ? "border-white/10 bg-[#0A0A0A] text-white placeholder:text-white/55"
                : "border-[#141414]/18 bg-[#F7F6F3] text-[#141414] placeholder:text-[#4A4741]"
            }`}
          />
        </label>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5 lg:min-w-[420px]">
          <CategoryButton
            label="All"
            selected={category === "all"}
            border={border}
            isDark={isDark}
            onClick={() => chooseCategory("all")}
          />
          {TARGET_CATEGORIES.map((item) => (
            <CategoryButton
              key={item.value}
              label={item.label}
              selected={category === item.value}
              border={border}
              isDark={isDark}
              onClick={() => chooseCategory(item.value)}
            />
          ))}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {targets.error && (
          <StatusLine
            icon="error"
            className={errorClass}
            text="Target registry unavailable"
          />
        )}
        {targets.refreshError && (
          <StatusLine
            icon="error"
            className={errorClass}
            text="Target refresh failed"
          />
        )}
        {targets.refreshResult && (
          <StatusLine
            icon="ok"
            className={okClass}
            text={`${targets.refreshResult.count} targets refreshed`}
          />
        )}
        {!targets.error &&
          !targets.isLoading &&
          targets.targets.length === 0 && (
            <StatusLine
              icon="error"
              className={warnClass}
              text="No targets loaded"
            />
          )}
        {targets.isLoading && (
          <div
            className={`h-28 animate-pulse rounded-lg ${isDark ? "bg-white/5" : "bg-[#141414]/5"}`}
          />
        )}
        {!targets.isLoading &&
          targets.targets.length > 0 &&
          filteredTargets.length === 0 && (
            <StatusLine
              icon="error"
              className={warnClass}
              text="No targets match this search"
            />
          )}
        {!targets.isLoading &&
          visibleTargets.map((target) => (
            <PrivacyTargetCard
              key={target.id}
              target={target}
              selected={targets.selectedIds.includes(target.id)}
              onToggle={() => targets.toggleTarget(target)}
              border={border}
              panel={isDark ? "bg-[#0A0A0A]/60" : "bg-white/55"}
              muted={muted}
              isDark={isDark}
            />
          ))}
        {hiddenTargetCount > 0 && (
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className={`inline-flex min-h-11 w-full items-center justify-center rounded-lg border px-3 text-sm transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border}`}
          >
            Show all {filteredTargets.length} matches
          </button>
        )}
        {showAll && filteredTargets.length > COLLAPSED_TARGET_LIMIT && (
          <button
            type="button"
            onClick={() => setShowAll(false)}
            className={`inline-flex min-h-11 w-full items-center justify-center rounded-lg border px-3 text-sm transition hover:border-emerald-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:hover:border-emerald-300/50 dark:focus-visible:outline-emerald-300 ${border}`}
          >
            Show fewer
          </button>
        )}
      </div>

      <div
        aria-live="polite"
        className={`mt-4 rounded-lg border px-3 py-2 text-sm font-medium ${targets.selectedCount > 0 ? okClass : warnClass}`}
      >
        {statusText}
      </div>
    </section>
  );
}

function CategoryButton({
  label,
  selected,
  border,
  isDark,
  onClick,
}: {
  label: string;
  selected: boolean;
  border: string;
  isDark: boolean;
  onClick: () => void;
}) {
  const selectedClass = isDark
    ? "border-white bg-white text-[#0A0A0A]"
    : "border-[#141414] bg-[#141414] text-[#F7F6F3]";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-h-11 rounded-lg border px-2 text-sm font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700 dark:focus-visible:outline-emerald-300 ${
        selected ? selectedClass : border
      }`}
    >
      {label}
    </button>
  );
}
