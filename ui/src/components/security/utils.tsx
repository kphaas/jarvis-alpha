import type {
  JwtCheck,
  RlsStatus,
  ChildProfileStatus,
  Perimeter,
  CertRow,
} from '../../types/security'

export const R_SCORE = 56
export const C_SCORE = 2 * Math.PI * R_SCORE

export function certPoints(certs: CertRow[] | null): number {
  if (!certs?.length) return 0
  const days = certs.map((c) => c.days_remaining)
  if (days.some((d) => d < 15)) return 0
  if (days.some((d) => d < 30)) return 10
  return 15
}

export function jwtPoints(jwt: JwtCheck | null): number {
  if (!jwt) return 0
  const f = jwt.failing
  if (f === 0) return 15
  if (f === 1) return 8
  return 0
}

export function rlsPoints(rls: RlsStatus | null): number {
  if (!rls || rls.total_tables <= 0) return 0
  return (rls.rls_enabled / rls.total_tables) * 15
}

export function corsPoints(perimeter: Perimeter | null): number {
  if (!perimeter) return 0
  return perimeter.cors.locked ? 10 : 0
}

export function childPoints(child: ChildProfileStatus | null): number {
  if (!child?.profiles?.length) return 0
  const ps = child.profiles
  if (ps.every((p) => p.db_layer === true)) return 10
  if (ps.every((p) => p.app_layer === true && p.db_layer === false)) return 5
  return 0
}

export function tailscalePoints(perimeter: Perimeter | null): number {
  if (!perimeter) return 0
  return perimeter.tailscale.active ? 10 : 0
}

export function portPoints(perimeter: Perimeter | null): number {
  if (!perimeter?.ports?.length) return 0
  const allMatch = perimeter.ports.every((p) => p.reachable === p.expected)
  return allMatch ? 10 : 5
}

export function honeypotPoints(totalHits: number | null): number {
  if (totalHits === null) return 0
  if (totalHits === 0) return 5
  if (totalHits <= 5) return 3
  return 0
}

export function computePostureScore(
  jwt: JwtCheck | null,
  rls: RlsStatus | null,
  child: ChildProfileStatus | null,
  perimeter: Perimeter | null,
  certs: CertRow[] | null,
  honeypotTotalHits: number | null
): { earned: number; displayScore: number; reserved: number } {
  const earned =
    jwtPoints(jwt) +
    rlsPoints(rls) +
    childPoints(child) +
    corsPoints(perimeter) +
    tailscalePoints(perimeter) +
    portPoints(perimeter) +
    certPoints(certs) +
    honeypotPoints(honeypotTotalHits)
  const reserved = 10
  const displayScore = Math.min(earned, 100 - reserved)
  return { earned, displayScore, reserved }
}

export function scoreColor(displayScore: number, isDark: boolean): string {
  if (displayScore >= 70) return isDark ? '#22c55e' : '#16a34a'
  if (displayScore >= 40) return isDark ? '#f59e0b' : '#d97706'
  return isDark ? '#ef4444' : '#dc2626'
}

export function certDayTextClass(days: number): string {
  if (days < 15) return 'text-rose-400'
  if (days < 30) return 'text-amber-400'
  return 'text-emerald-400'
}

export function certBarPct(days: number): number {
  return Math.min(100, (days / 90) * 100)
}

export function certBarColor(days: number): string {
  if (days < 15) return 'bg-rose-500'
  if (days < 30) return 'bg-amber-500'
  return 'bg-emerald-500'
}

export function SectionSkeleton({ border, subtle }: { border: string; subtle: string }) {
  return (
    <div className={`animate-pulse rounded-2xl border ${border} ${subtle} p-8`}>
      <div className="h-3 w-32 rounded-full bg-white/10" />
      <div className="mt-4 h-24 rounded-xl bg-white/5" />
    </div>
  )
}

export function SectionUnavailable({ border, subtle }: { border: string; subtle: string }) {
  return (
    <div className={`rounded-2xl border ${border} ${subtle} p-8 text-center`}>
      <p className="text-xs font-mono opacity-40">Service unavailable</p>
    </div>
  )
}

export function relativeAccessedLabel(iso: string): string {
  try {
    const d = new Date(iso)
    const now = new Date()
    const ms = now.getTime() - d.getTime()
    const sec = Math.floor(ms / 1000)
    if (sec < 60) return `${sec}s ago`
    const min = Math.floor(sec / 60)
    if (min < 60) return `${min}m ago`
    const hr = Math.floor(min / 60)
    if (hr < 24) return `${hr}h ago`
    return d.toLocaleDateString()
  } catch {
    return iso
  }
}

export function secretSourceBadgeClass(source: string, isDark: boolean): string {
  if (source === "get_secret") {
    return isDark
      ? "border-sky-500/30 bg-sky-500/15 text-sky-400"
      : "border-sky-600/30 bg-sky-500/10 text-sky-700";
  }
  if (source === "rotation_success") {
    return "border-emerald-500/30 bg-emerald-500/15 text-emerald-400";
  }
  if (source === "rotation_rolled_back") {
    return "border-amber-500/30 bg-amber-500/15 text-amber-400";
  }
  return isDark
    ? "border-white/10 bg-white/5 text-zinc-400"
    : "border-[#141414]/15 bg-[#141414]/5 text-zinc-600";
}

export interface SecurityThemeProps {
  isDark: boolean
  border: string
  subtle: string
  fg: string
  muted: string
}

import type { RotatableKey } from '../../types/security'

export function validateKeyFormat(key: RotatableKey, value: string): string | null {
  if (!value) return "Key value is required";
  if (value.length < key.min_length) {
    return `Key must be at least ${key.min_length} characters`;
  }
  if (key.prefix && !value.startsWith(key.prefix)) {
    return `Key must start with "${key.prefix}"`;
  }
  return null;
}
