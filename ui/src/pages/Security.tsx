import { useState, useEffect, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import {
  Shield,
  Key,
  Globe,
  Lock,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Loader2,
  Users,
  Radio,
  Server,
  RotateCw,
} from "lucide-react";
import { apiJson } from "../lib/apiFetch";
import { useAppStore } from "../store";

const TABS = ["Overview", "Identity", "Network", "Certs", "Keys", "Events"] as const;
type TabId = (typeof TABS)[number];

const REFRESH_MS = 30_000;

/** sub-tab navigation — local state only (no router) */

interface JwtCheck {
  total: number;
  passing: number;
  failing: number;
  checks: {
    route: string;
    expected: number;
    actual: number;
    pass: boolean;
    type: string;
  }[];
}

interface RlsStatus {
  total_tables: number;
  rls_enabled: number;
  rls_disabled: number;
  tables: { table: string; rls: string; policy: string }[];
}

interface ChildProfile {
  name: string;
  age: number;
  app_layer: boolean;
  db_layer: boolean;
  content_filter: boolean;
  notes: string;
}

interface ChildProfileStatus {
  profiles: ChildProfile[];
  overall: string;
  recommendation: string;
}

interface PortCheck {
  node: string;
  port: number;
  service: string;
  reachable: boolean;
  expected: boolean;
}

interface Perimeter {
  cors: { allowed_origins: string[]; locked: boolean };
  ports: PortCheck[];
  tailscale: { active: boolean; node_count: number };
}

interface CertRow {
  node: string;
  domain: string;
  expires: string;
  days_remaining: number;
  status: string;
  source: string;
}

interface LogEntry {
  ts: string;
  level: string;
  service: string;
  node: string;
  message: string;
}

interface LogsQueryResponse {
  status: string;
  entries?: LogEntry[];
}

interface RotatableKey {
  key_name: string;
  provider: string;
  prefix: string;
  min_length: number;
}

interface RotationResult {
  status: string;
  rotation_id: string;
  key_name: string;
  error: string | null;
  old_key_health: string | null;
  new_key_health: string | null;
}

interface SecretAuditEvent {
  key: string;
  source: string;
  accessed_at: string;
  node: string;
}

interface SecretsAuditResponse {
  total_events: number;
  unique_keys?: number;
  events: SecretAuditEvent[];
  error?: string;
}

const TAB_ICONS = {
  Overview: Shield,
  Identity: Key,
  Network: Globe,
  Certs: Lock,
  Keys: RotateCw,
  Events: AlertTriangle,
} as const;

const R_SCORE = 56;
const C_SCORE = 2 * Math.PI * R_SCORE;

function certPoints(certs: CertRow[] | null): number {
  if (!certs?.length) return 0;
  const days = certs.map((c) => c.days_remaining);
  if (days.some((d) => d < 15)) return 0;
  if (days.some((d) => d < 30)) return 10;
  return 15;
}

function jwtPoints(jwt: JwtCheck | null): number {
  if (!jwt) return 0;
  const f = jwt.failing;
  if (f === 0) return 15;
  if (f === 1) return 8;
  return 0;
}

function rlsPoints(rls: RlsStatus | null): number {
  if (!rls || rls.total_tables <= 0) return 0;
  return (rls.rls_enabled / rls.total_tables) * 15;
}

function corsPoints(perimeter: Perimeter | null): number {
  if (!perimeter) return 0;
  return perimeter.cors.locked ? 10 : 0;
}

function childPoints(child: ChildProfileStatus | null): number {
  if (!child?.profiles?.length) return 0;
  const ps = child.profiles;
  if (ps.every((p) => p.db_layer === true)) return 10;
  if (ps.every((p) => p.app_layer === true && p.db_layer === false)) return 5;
  return 0;
}

function tailscalePoints(perimeter: Perimeter | null): number {
  if (!perimeter) return 0;
  return perimeter.tailscale.active ? 10 : 0;
}

function portPoints(perimeter: Perimeter | null): number {
  if (!perimeter?.ports?.length) return 0;
  const allMatch = perimeter.ports.every((p) => p.reachable === p.expected);
  return allMatch ? 10 : 5;
}

/** Security posture score — raw points 0..85 (15 reserved for future checks) */
function computePostureScore(
  jwt: JwtCheck | null,
  rls: RlsStatus | null,
  child: ChildProfileStatus | null,
  perimeter: Perimeter | null,
  certs: CertRow[] | null
): { earned: number; displayScore: number; reserved: number } {
  const earned =
    certPoints(certs) +
    jwtPoints(jwt) +
    rlsPoints(rls) +
    corsPoints(perimeter) +
    childPoints(child) +
    tailscalePoints(perimeter) +
    portPoints(perimeter);
  const reserved = 15;
  const maxCurrent = 85;
  const displayScore = Math.round(Math.min(100, (earned / maxCurrent) * 100));
  return { earned, displayScore, reserved };
}

function scoreColor(displayScore: number, isDark: boolean): string {
  if (displayScore >= 80) return isDark ? "#34d399" : "#059669";
  if (displayScore >= 60) return isDark ? "#fbbf24" : "#d97706";
  return isDark ? "#f87171" : "#dc2626";
}

function certDayTextClass(days: number): string {
  if (days > 30) return "text-emerald-400";
  if (days >= 15) return "text-amber-400";
  return "text-rose-400";
}

function certBarPct(days: number): number {
  return Math.min(100, Math.max(0, (days / 90) * 100));
}

function certBarColor(days: number): string {
  if (days > 30) return "#34d399";
  if (days >= 15) return "#f59e0b";
  return "#ef4444";
}

function SectionSkeleton({ border, subtle }: { border: string; subtle: string }) {
  return (
    <div className={`rounded-2xl border ${border} ${subtle} p-8 flex items-center justify-center gap-2`}>
      <Loader2 className="w-5 h-5 animate-spin opacity-40" />
      <span className="text-xs font-mono opacity-40">Loading…</span>
    </div>
  );
}

function SectionUnavailable({ border, subtle }: { border: string; subtle: string }) {
  return (
    <div className={`rounded-2xl border ${border} ${subtle} p-6 text-center text-sm opacity-50 font-mono`}>
      Data unavailable
    </div>
  );
}

function validateKeyFormat(key: RotatableKey, value: string): string | null {
  if (!value) return null;
  if (key.prefix && !value.startsWith(key.prefix)) {
    return `Key must start with '${key.prefix}'`;
  }
  if (value.length < key.min_length) {
    return `Key must be at least ${key.min_length} characters (currently ${value.length})`;
  }
  if (!value.split("").every((ch) => ch.charCodeAt(0) < 128)) {
    return "Key must be ASCII only";
  }
  return null;
}

function relativeAccessedLabel(iso: string): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const secs = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  if (h < 48) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function secretSourceBadgeClass(source: string, isDark: boolean): string {
  if (source === "env") {
    return isDark
      ? "border-blue-500/30 bg-blue-500/15 text-blue-400"
      : "border-blue-600/30 bg-blue-500/10 text-blue-700";
  }
  if (source === "file") {
    return isDark
      ? "border-zinc-500/30 bg-zinc-500/15 text-zinc-400"
      : "border-zinc-400/40 bg-zinc-500/10 text-zinc-600";
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

export default function Security() {
  const { theme } = useAppStore();
  const isDark = theme === "dark";
  const border = isDark ? "border-white/10" : "border-[#141414]/10";
  const subtle = isDark ? "bg-white/5" : "bg-[#141414]/5";
  const fg = isDark ? "text-white/90" : "text-[#141414]/90";
  const muted = isDark ? "text-white/45" : "text-[#141414]/50";

  const [activeTab, setActiveTab] = useState<TabId>("Overview");

  const [jwt, setJwt] = useState<JwtCheck | null>(null);
  const [rls, setRls] = useState<RlsStatus | null>(null);
  const [child, setChild] = useState<ChildProfileStatus | null>(null);
  const [perimeter, setPerimeter] = useState<Perimeter | null>(null);
  const [certs, setCerts] = useState<CertRow[] | null>(null);
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);

  const [loadJwt, setLoadJwt] = useState(true);
  const [loadRls, setLoadRls] = useState(true);
  const [loadChild, setLoadChild] = useState(true);
  const [loadPerimeter, setLoadPerimeter] = useState(true);
  const [loadCerts, setLoadCerts] = useState(true);
  const [loadLogs, setLoadLogs] = useState(true);

  const [errJwt, setErrJwt] = useState(false);
  const [errRls, setErrRls] = useState(false);
  const [errChild, setErrChild] = useState(false);
  const [errPerimeter, setErrPerimeter] = useState(false);
  const [errCerts, setErrCerts] = useState(false);
  const [errLogs, setErrLogs] = useState(false);

  const [rotatableKeys, setRotatableKeys] = useState<RotatableKey[]>([]);
  const [secretsAuditEvents, setSecretsAuditEvents] = useState<SecretAuditEvent[]>([]);
  const [loadRotatableKeys, setLoadRotatableKeys] = useState(true);
  const [loadSecretsAudit, setLoadSecretsAudit] = useState(true);
  const [errRotatableKeys, setErrRotatableKeys] = useState(false);
  const [errSecretsAudit, setErrSecretsAudit] = useState(false);

  const [rotatingKey, setRotatingKey] = useState<RotatableKey | null>(null);
  const [newKeyValue, setNewKeyValue] = useState("");
  const [rotationLoading, setRotationLoading] = useState(false);
  const [rotationResult, setRotationResult] = useState<RotationResult | null>(null);
  const [formatError, setFormatError] = useState<string | null>(null);

  const mounted = useRef(true);
  const fetchRunning = useRef(false);

  const fetchAll = useCallback(async (showLoading: boolean) => {
    if (!mounted.current || fetchRunning.current) return;
    fetchRunning.current = true;

    if (showLoading) {
      setLoadJwt(true);
      setLoadRls(true);
      setLoadChild(true);
      setLoadPerimeter(true);
      setLoadCerts(true);
      setLoadLogs(true);
      setLoadRotatableKeys(true);
      setLoadSecretsAudit(true);
    }

    try {
      const [j, r, c, p, cert, logs, rk, sa] = await Promise.all([
        apiJson<JwtCheck>("/v1/security/jwt-check")
          .then((data) => ({ ok: true as const, data }))
          .catch(() => ({ ok: false as const })),
        apiJson<RlsStatus>("/v1/security/rls-status")
          .then((data) => ({ ok: true as const, data }))
          .catch(() => ({ ok: false as const })),
        apiJson<ChildProfileStatus>("/v1/security/child-profiles")
          .then((data) => ({ ok: true as const, data }))
          .catch(() => ({ ok: false as const })),
        apiJson<Perimeter>("/v1/security/perimeter")
          .then((data) => ({ ok: true as const, data }))
          .catch(() => ({ ok: false as const })),
        apiJson<CertRow[]>("/v1/mesh/certs")
          .then((data) => ({ ok: true as const, data }))
          .catch(() => ({ ok: false as const })),
        apiJson<LogsQueryResponse>(
          "/v1/logs/query?limit=20&level=WARNING&service=alpha_brain"
        )
          .then((data) => ({ ok: true as const, data }))
          .catch(() => ({ ok: false as const })),
        apiJson<{ keys: RotatableKey[] }>("/v1/security/rotatable-keys")
          .then((data) => ({ ok: true as const, data }))
          .catch(() => ({ ok: false as const, data: { keys: [] as RotatableKey[] } })),
        apiJson<SecretsAuditResponse>("/v1/security/secrets-audit?limit=20")
          .then((data) => ({ ok: true as const, data }))
          .catch(() => ({ ok: false as const })),
      ]);

      if (!mounted.current) return;

      if (j.ok) {
        setJwt(j.data);
        setErrJwt(false);
      } else {
        setJwt(null);
        setErrJwt(true);
      }
      if (r.ok) {
        setRls(r.data);
        setErrRls(false);
      } else {
        setRls(null);
        setErrRls(true);
      }
      if (c.ok) {
        setChild(c.data);
        setErrChild(false);
      } else {
        setChild(null);
        setErrChild(true);
      }
      if (p.ok) {
        setPerimeter(p.data);
        setErrPerimeter(false);
      } else {
        setPerimeter(null);
        setErrPerimeter(true);
      }
      if (cert.ok) {
        setCerts(cert.data);
        setErrCerts(false);
      } else {
        setCerts(null);
        setErrCerts(true);
      }
      if (logs.ok) {
        const data = logs.data;
        if (data.status !== "error") {
          setLogEntries(data.entries ?? []);
          setErrLogs(false);
        } else {
          setLogEntries([]);
          setErrLogs(true);
        }
      } else {
        setLogEntries([]);
        setErrLogs(true);
      }

      if (rk.ok) {
        setRotatableKeys(rk.data.keys ?? []);
        setErrRotatableKeys(false);
      } else {
        setRotatableKeys([]);
        setErrRotatableKeys(true);
      }
      if (sa.ok) {
        setSecretsAuditEvents(sa.data.events ?? []);
        setErrSecretsAudit(Boolean(sa.data.error));
      } else {
        setSecretsAuditEvents([]);
        setErrSecretsAudit(true);
      }
    } finally {
      fetchRunning.current = false;
      if (mounted.current && showLoading) {
        setLoadJwt(false);
        setLoadRls(false);
        setLoadChild(false);
        setLoadPerimeter(false);
        setLoadCerts(false);
        setLoadLogs(false);
        setLoadRotatableKeys(false);
        setLoadSecretsAudit(false);
      }
    }
  }, []);

  const closeRotationModal = useCallback(() => {
    setRotatingKey(null);
    setNewKeyValue("");
    setFormatError(null);
    setRotationResult(null);
    setRotationLoading(false);
  }, []);

  const handleRotate = useCallback(async () => {
    if (!rotatingKey || !newKeyValue) return;
    setRotationLoading(true);
    setRotationResult(null);
    try {
      const result = await apiJson<RotationResult>("/v1/security/rotate-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key_name: rotatingKey.key_name,
          new_value: newKeyValue,
        }),
      });
      setRotationResult(result);
      if (result.status === "success") {
        setNewKeyValue("");
      }
    } catch (e) {
      setRotationResult({
        status: "error",
        rotation_id: "",
        key_name: rotatingKey.key_name,
        error: e instanceof Error ? e.message : "Rotation failed",
        old_key_health: null,
        new_key_health: null,
      });
    } finally {
      setRotationLoading(false);
    }
  }, [rotatingKey, newKeyValue]);

  useEffect(() => {
    mounted.current = true;
    void fetchAll(true);
    const id = setInterval(() => void fetchAll(false), REFRESH_MS);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, [fetchAll]);

  const { earned, displayScore, reserved } = computePostureScore(
    jwt,
    rls,
    child,
    perimeter,
    certs
  );
  const strokeColor = scoreColor(displayScore, isDark);
  /** posture arc: earned points are 0..85 of 100 — leaves 15% track for reserved future checks */
  const dashEarned = (earned / 100) * C_SCORE;

  const jwtPassing = jwt?.passing ?? 0;
  const jwtTotal = jwt?.total ?? 0;
  const portPass =
    perimeter?.ports.filter((p) => p.reachable === p.expected).length ?? 0;
  const portTotal = perimeter?.ports.length ?? 0;
  const checksPassing = jwtPassing + portPass;
  const checksTotal = jwtTotal + portTotal;

  const shortestCertDays =
    certs && certs.length ? Math.min(...certs.map((c) => c.days_remaining)) : null;

  const sortedCerts = certs
    ? [...certs].sort((a, b) => a.days_remaining - b.days_remaining)
    : [];

  const protectedTables = rls?.tables.filter((t) => t.rls === "enabled") ?? [];
  const unprotectedTables = rls?.tables.filter((t) => t.rls !== "enabled") ?? [];

  const nodeOrder = ["brain", "gateway", "endpoint", "sandbox"];
  const portsByNode = perimeter
    ? [...perimeter.ports].sort(
        (a, b) => nodeOrder.indexOf(a.node) - nodeOrder.indexOf(b.node) || a.port - b.port
      )
    : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6 max-w-5xl"
    >
      <div>
        <h1 className="font-serif italic text-3xl">Security</h1>
        <p className="text-[10px] font-mono uppercase opacity-50 mt-1">
          Posture, identity, network perimeter, TLS, events
        </p>
      </div>

      {/* sub-tab pills */}
      <div className="flex flex-wrap gap-2">
        {TABS.map((tab) => {
          const Icon = TAB_ICONS[tab];
          const active = activeTab === tab;
          return (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-mono transition-colors ${
                border
              } ${
                active
                  ? isDark
                    ? "bg-white/10 font-bold text-white"
                    : "bg-black/10 font-bold text-[#141414]"
                  : `${subtle} opacity-60 hover:opacity-90`
              }`}
            >
              {tab === "Keys" ? (
                <RotateCw className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
              ) : (
                <Icon className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
              )}
              {tab}
            </button>
          );
        })}
      </div>

      {activeTab === "Overview" && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-8"
        >
          <section className="flex flex-col items-center gap-4">
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest self-start">
              Security posture score
            </p>
            {loadJwt && loadPerimeter && loadCerts && loadRls && loadChild && !jwt ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : (
              <div className="relative w-[200px] h-[200px] flex items-center justify-center">
                <svg width="200" height="200" className="-rotate-90">
                  <circle
                    cx="100"
                    cy="100"
                    r={R_SCORE}
                    fill="none"
                    stroke={isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.1)"}
                    strokeWidth="10"
                  />
                  <motion.circle
                    cx="100"
                    cy="100"
                    r={R_SCORE}
                    fill="none"
                    stroke={strokeColor}
                    strokeWidth="10"
                    strokeLinecap="round"
                    strokeDasharray={`${dashEarned} ${C_SCORE}`}
                    initial={{ strokeDashoffset: C_SCORE }}
                    animate={{ strokeDashoffset: C_SCORE - dashEarned }}
                    transition={{ duration: 0.9, ease: "easeOut" }}
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                  <span
                    className="text-4xl font-bold font-mono tabular-nums"
                    style={{ color: strokeColor }}
                  >
                    {displayScore}
                  </span>
                  <span className={`text-[9px] font-mono uppercase ${muted}`}>of 100</span>
                </div>
              </div>
            )}
            <p className={`text-xs font-mono ${muted} text-center`}>
              {checksTotal > 0
                ? `${checksPassing} of ${checksTotal} checks passing`
                : "Collecting check data…"}
            </p>
            <p className={`text-[10px] font-mono ${muted} text-center max-w-md`}>
              <span className="opacity-70">{reserved} pts reserved</span> (secrets audit, honeypot, key rotation) —{" "}
              <span className="text-zinc-500">locked</span>
            </p>
          </section>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <motion.button
              type="button"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.05 }}
              onClick={() => setActiveTab("Identity")}
              className={`rounded-2xl border ${border} ${subtle} p-5 text-left hover:opacity-95 transition-opacity`}
            >
              <Key className="w-4 h-4 opacity-50 mb-3" />
              {loadJwt && !jwt ? (
                <Loader2 className="w-6 h-6 animate-spin opacity-30 my-2" />
              ) : errJwt || !jwt ? (
                <p className="text-sm opacity-40 font-mono">Unavailable</p>
              ) : (
                <>
                  <p className={`text-3xl font-bold font-mono ${fg}`}>
                    {jwt.passing}/{jwt.total}
                  </p>
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">
                    JWT coverage
                  </p>
                  <div className="mt-2 flex justify-end">
                    {jwt.failing === 0 ? (
                      <CheckCircle className="w-5 h-5 text-emerald-400" />
                    ) : (
                      <XCircle className="w-5 h-5 text-rose-400" />
                    )}
                  </div>
                </>
              )}
            </motion.button>

            <motion.button
              type="button"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              onClick={() => setActiveTab("Identity")}
              className={`rounded-2xl border ${border} ${subtle} p-5 text-left hover:opacity-95 transition-opacity`}
            >
              <Server className="w-4 h-4 opacity-50 mb-3" />
              {loadRls && !rls ? (
                <Loader2 className="w-6 h-6 animate-spin opacity-30 my-2" />
              ) : errRls || !rls ? (
                <p className="text-sm opacity-40 font-mono">Unavailable</p>
              ) : (
                <>
                  <p className={`text-3xl font-bold font-mono ${fg}`}>
                    {rls.rls_enabled}/{rls.total_tables}
                  </p>
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">
                    RLS coverage
                  </p>
                  <p className="text-xs font-mono opacity-50 mt-2">
                    {rls.total_tables
                      ? `${Math.round((rls.rls_enabled / rls.total_tables) * 100)}% protected`
                      : "—"}
                  </p>
                </>
              )}
            </motion.button>

            <motion.button
              type="button"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 }}
              onClick={() => setActiveTab("Certs")}
              className={`rounded-2xl border ${border} ${subtle} p-5 text-left hover:opacity-95 transition-opacity`}
            >
              <Lock className="w-4 h-4 opacity-50 mb-3" />
              {loadCerts && !certs ? (
                <Loader2 className="w-6 h-6 animate-spin opacity-30 my-2" />
              ) : errCerts || !certs?.length ? (
                <p className="text-sm opacity-40 font-mono">Unavailable</p>
              ) : (
                <>
                  <p className={`text-3xl font-bold font-mono ${certDayTextClass(shortestCertDays ?? 0)}`}>
                    {shortestCertDays}d
                  </p>
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">
                    TLS certs (shortest)
                  </p>
                </>
              )}
            </motion.button>

            <motion.button
              type="button"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              onClick={() => setActiveTab("Network")}
              className={`rounded-2xl border ${border} ${subtle} p-5 text-left hover:opacity-95 transition-opacity`}
            >
              <Radio className="w-4 h-4 opacity-50 mb-3" />
              {loadPerimeter && !perimeter ? (
                <Loader2 className="w-6 h-6 animate-spin opacity-30 my-2" />
              ) : errPerimeter || !perimeter ? (
                <p className="text-sm opacity-40 font-mono">Unavailable</p>
              ) : (
                <>
                  <p className={`text-3xl font-bold font-mono ${fg}`}>
                    {perimeter.tailscale.node_count}
                  </p>
                  <p className="text-[10px] font-mono uppercase opacity-40 mt-1">
                    Network · Tailscale nodes
                  </p>
                  <p className="text-xs font-mono opacity-50 mt-2">
                    CORS {perimeter.cors.locked ? "locked" : "open"}
                  </p>
                </>
              )}
            </motion.button>
          </div>
        </motion.div>
      )}

      {activeTab === "Identity" && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-8"
        >
          <section>
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest">
                JWT enforcement
              </p>
              {!loadJwt && jwt && (
                <span className="text-xs font-mono opacity-60">
                  {jwt.passing}/{jwt.total} routes enforced
                </span>
              )}
            </div>
            {loadJwt && !jwt ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errJwt || !jwt ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
                <table className="w-full text-xs">
                  <thead>
                    <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                      <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                        Route
                      </th>
                      <th className="text-center px-2 py-2 font-mono uppercase opacity-40">
                        Expected
                      </th>
                      <th className="text-center px-2 py-2 font-mono uppercase opacity-40">
                        Actual
                      </th>
                      <th className="text-center px-4 py-2 font-mono uppercase opacity-40">
                        Result
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {jwt.checks.map((c) => (
                      <tr key={c.route}>
                        <td className="px-4 py-2 font-mono">{c.route}</td>
                        <td className="px-2 py-2 text-center font-mono opacity-70">
                          {c.expected}
                        </td>
                        <td className="px-2 py-2 text-center font-mono">{c.actual}</td>
                        <td className="px-4 py-2 text-center">
                          {c.pass ? (
                            <CheckCircle className="w-4 h-4 text-emerald-400 inline-block" />
                          ) : (
                            <XCircle className="w-4 h-4 text-rose-400 inline-block" />
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest">
                RLS status
              </p>
              {!loadRls && rls && (
                <span className="text-xs font-mono opacity-60">
                  {rls.rls_enabled}/{rls.total_tables} tables with RLS
                </span>
              )}
            </div>
            {loadRls && !rls ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errRls || !rls ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className="space-y-6">
                <div>
                  <p className="text-[10px] font-mono uppercase opacity-50 mb-2">Protected</p>
                  <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            Table
                          </th>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            RLS
                          </th>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            Policy
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {protectedTables.map((t) => (
                          <tr key={t.table}>
                            <td className="px-4 py-2 font-mono">{t.table}</td>
                            <td className="px-4 py-2">
                              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/15 text-emerald-400">
                                enabled
                              </span>
                            </td>
                            <td className="px-4 py-2 font-mono opacity-80">{t.policy}</td>
                          </tr>
                        ))}
                        {protectedTables.length === 0 && (
                          <tr>
                            <td colSpan={3} className="px-4 py-4 text-center opacity-40 font-mono">
                              None
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
                <div>
                  <p className="text-[10px] font-mono uppercase opacity-50 mb-2">Unprotected</p>
                  <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            Table
                          </th>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            RLS
                          </th>
                          <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                            Policy
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {unprotectedTables.map((t) => (
                          <tr key={t.table}>
                            <td className="px-4 py-2 font-mono">{t.table}</td>
                            <td className="px-4 py-2">
                              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-white/10 bg-white/5 text-zinc-400">
                                disabled
                              </span>
                            </td>
                            <td className="px-4 py-2 font-mono opacity-80">{t.policy}</td>
                          </tr>
                        ))}
                        {unprotectedTables.length === 0 && (
                          <tr>
                            <td colSpan={3} className="px-4 py-4 text-center opacity-40 font-mono">
                              None
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </section>

          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
              Child profiles
            </p>
            {loadChild && !child ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errChild || !child ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {child.profiles.map((p) => (
                    <div
                      key={p.name}
                      className={`rounded-2xl border ${border} ${subtle} p-5 space-y-3`}
                    >
                      <div className="flex items-center gap-2">
                        <Shield className="w-4 h-4 text-emerald-400/80" />
                        <span className="font-bold">{p.name}</span>
                        <span className={`text-xs font-mono ${muted}`}>age {p.age}</span>
                      </div>
                      <div className="flex flex-wrap gap-2 text-[10px] font-mono">
                        <span
                          className={`px-2 py-0.5 rounded border ${
                            p.app_layer
                              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                              : "border-rose-500/30 bg-rose-500/15 text-rose-400"
                          }`}
                        >
                          app_layer {p.app_layer ? "on" : "off"}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded border ${
                            p.db_layer
                              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                              : "border-rose-500/30 bg-rose-500/15 text-rose-400"
                          }`}
                        >
                          db_layer {p.db_layer ? "on" : "off"}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded border ${
                            p.content_filter
                              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400"
                              : "border-rose-500/30 bg-rose-500/15 text-rose-400"
                          }`}
                        >
                          content_filter {p.content_filter ? "on" : "off"}
                        </span>
                      </div>
                      <p className={`text-xs ${muted} leading-relaxed`}>{p.notes}</p>
                    </div>
                  ))}
                </div>
                {child.overall !== "full" && (
                  <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200/90">
                    {child.recommendation}
                  </div>
                )}
              </div>
            )}
          </section>
        </motion.div>
      )}

      {activeTab === "Network" && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-8"
        >
          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
              CORS policy
            </p>
            {loadPerimeter && !perimeter ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errPerimeter || !perimeter ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} p-5 space-y-3`}>
                <div className="flex items-center gap-2">
                  {perimeter.cors.locked ? (
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/15 text-emerald-400">
                      LOCKED
                    </span>
                  ) : (
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-rose-500/30 bg-rose-500/15 text-rose-400">
                      OPEN
                    </span>
                  )}
                </div>
                <ul className="text-xs font-mono space-y-1 opacity-80">
                  {perimeter.cors.allowed_origins.map((o) => (
                    <li key={o}>{o}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
              Port scan
            </p>
            {loadPerimeter && !perimeter ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errPerimeter || !perimeter ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
                <table className="w-full text-xs">
                  <thead>
                    <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                      <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                        Node
                      </th>
                      <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                        Port
                      </th>
                      <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                        Service
                      </th>
                      <th className="text-center px-2 py-2 font-mono uppercase opacity-40">
                        Reachable
                      </th>
                      <th className="text-center px-2 py-2 font-mono uppercase opacity-40">
                        Expected
                      </th>
                      <th className="text-center px-4 py-2 font-mono uppercase opacity-40">
                        Match
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {portsByNode.map((p) => {
                      const match = p.reachable === p.expected;
                      return (
                        <tr key={`${p.node}-${p.port}`}>
                          <td className="px-4 py-2 font-mono capitalize">{p.node}</td>
                          <td className="px-2 py-2 font-mono">{p.port}</td>
                          <td className="px-2 py-2 font-mono opacity-80">{p.service}</td>
                          <td className="px-2 py-2 text-center font-mono">
                            {p.reachable ? "yes" : "no"}
                          </td>
                          <td className="px-2 py-2 text-center font-mono">
                            {p.expected ? "yes" : "no"}
                          </td>
                          <td className="px-4 py-2 text-center">
                            {match ? (
                              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/15 text-emerald-400">
                                MATCH
                              </span>
                            ) : (
                              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border border-rose-500/30 bg-rose-500/15 text-rose-400">
                                MISMATCH
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
              Tailscale
            </p>
            {loadPerimeter && !perimeter ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errPerimeter || !perimeter ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} p-6 flex flex-col sm:flex-row sm:items-center gap-4`}>
                <div>
                  {perimeter.tailscale.active ? (
                    <span className="text-sm font-mono font-bold px-3 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/15 text-emerald-400">
                      ACTIVE
                    </span>
                  ) : (
                    <span className="text-sm font-mono font-bold px-3 py-1.5 rounded-lg border border-zinc-500/30 bg-zinc-500/15 text-zinc-400">
                      INACTIVE
                    </span>
                  )}
                </div>
                <div className={`font-mono text-sm ${fg}`}>
                  <Users className="w-4 h-4 inline mr-2 opacity-50" />
                  {perimeter.tailscale.node_count} nodes in tailnet
                </div>
              </div>
            )}
          </section>
        </motion.div>
      )}

      {activeTab === "Certs" && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
          <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
            TLS certificates
          </p>
          {loadCerts && !certs ? (
            <SectionSkeleton border={border} subtle={subtle} />
          ) : errCerts || !certs?.length ? (
            <SectionUnavailable border={border} subtle={subtle} />
          ) : (
            <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
              <table className="w-full text-xs">
                <thead>
                  <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                    <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                      Node
                    </th>
                    <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                      Domain
                    </th>
                    <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                      Expires
                    </th>
                    <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                      Days
                    </th>
                    <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {sortedCerts.map((c) => (
                    <tr key={`${c.node}-${c.domain}`}>
                      <td className="px-4 py-3 font-mono capitalize">{c.node}</td>
                      <td className="px-2 py-3 font-mono opacity-90">{c.domain}</td>
                      <td className="px-2 py-3 font-mono opacity-70">
                        {c.expires ? new Date(c.expires).toLocaleDateString() : "—"}
                      </td>
                      <td className="px-2 py-3">
                        <span className={`font-mono font-bold ${certDayTextClass(c.days_remaining)}`}>
                          {c.days_remaining}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-col gap-1 min-w-[140px]">
                          <span className="text-[10px] font-mono uppercase opacity-60">
                            {c.status}
                          </span>
                          <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all"
                              style={{
                                width: `${certBarPct(c.days_remaining)}%`,
                                backgroundColor: certBarColor(c.days_remaining),
                              }}
                            />
                          </div>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </motion.div>
      )}

      {activeTab === "Keys" && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-8"
        >
          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-1">
              API key management
            </p>
            <p className={`text-xs font-mono ${muted} mb-4`}>
              Rotate cloud provider API keys with zero-downtime rollback
            </p>
            {loadRotatableKeys && rotatableKeys.length === 0 ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errRotatableKeys && rotatableKeys.length === 0 ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : rotatableKeys.length === 0 ? (
              <div className={`rounded-2xl border ${border} ${subtle} p-6 text-sm font-mono opacity-50`}>
                No rotatable keys returned from API
              </div>
            ) : (
              <div className="space-y-3">
                {rotatableKeys.map((k) => (
                  <div
                    key={k.key_name}
                    className={`rounded-2xl border ${border} ${subtle} px-5 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3`}
                  >
                    <div>
                      <p className="font-bold text-sm">{k.provider}</p>
                      <p className={`text-xs font-mono ${muted} mt-0.5`}>{k.key_name}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setRotatingKey(k);
                        setNewKeyValue("");
                        setFormatError(null);
                        setRotationResult(null);
                      }}
                      className={`inline-flex items-center justify-center gap-2 rounded-xl border ${border} px-4 py-2 text-xs font-mono font-bold hover:opacity-90 transition-opacity shrink-0`}
                    >
                      <RotateCw className="w-3.5 h-3.5" strokeWidth={2} />
                      Rotate
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
              Recent secret access
            </p>
            {loadSecretsAudit && secretsAuditEvents.length === 0 ? (
              <SectionSkeleton border={border} subtle={subtle} />
            ) : errSecretsAudit && secretsAuditEvents.length === 0 ? (
              <SectionUnavailable border={border} subtle={subtle} />
            ) : secretsAuditEvents.length === 0 ? (
              <div className={`rounded-2xl border ${border} ${subtle} p-6 text-sm font-mono opacity-50`}>
                No secret access events recorded
              </div>
            ) : (
              <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
                <table className="w-full text-xs">
                  <thead>
                    <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                      <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                        Key name
                      </th>
                      <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                        Source
                      </th>
                      <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                        Accessed
                      </th>
                      <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                        Node
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {secretsAuditEvents.map((ev, i) => (
                      <tr key={`${ev.key}-${ev.accessed_at}-${i}`}>
                        <td className="px-4 py-2 font-mono">{ev.key}</td>
                        <td className="px-2 py-2">
                          <span
                            className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${secretSourceBadgeClass(ev.source, isDark)}`}
                          >
                            {ev.source}
                          </span>
                        </td>
                        <td className="px-2 py-2 font-mono opacity-80">
                          {relativeAccessedLabel(ev.accessed_at)}
                        </td>
                        <td className="px-4 py-2 font-mono opacity-80">{ev.node}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {rotatingKey && (
            <div
              role="presentation"
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
              onClick={closeRotationModal}
            >
              <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="rotation-modal-title"
                className={`w-full max-w-lg rounded-2xl border p-6 shadow-xl ${
                  isDark ? "border-white/10 bg-zinc-900" : "border-[#141414]/15 bg-white"
                }`}
                onClick={(e) => e.stopPropagation()}
              >
                {!rotationResult ? (
                  <>
                    <div className="flex items-center gap-2 mb-1">
                      <Shield className="w-5 h-5 text-emerald-400/90 shrink-0" />
                      <h2 id="rotation-modal-title" className="font-serif italic text-xl">
                        Rotate {rotatingKey.provider} key
                      </h2>
                    </div>
                    <p className={`text-xs font-mono ${muted} mb-3`}>
                      Paste your new API key from the {rotatingKey.provider} dashboard
                    </p>
                    <p className={`text-xs leading-relaxed ${muted} mb-4`}>
                      The current key will be backed up. The new key will be tested against the
                      provider API. If the test fails, the old key will be restored automatically.
                    </p>
                    <label className="block text-[10px] font-mono uppercase opacity-50 mb-1.5">
                      New API key
                    </label>
                    <textarea
                      value={newKeyValue}
                      onChange={(e) => {
                        const v = e.target.value;
                        setNewKeyValue(v);
                        setFormatError(validateKeyFormat(rotatingKey, v));
                      }}
                      rows={3}
                      placeholder={`${rotatingKey.prefix}...`}
                      className={`w-full rounded-xl border font-mono text-sm p-3 resize-y min-h-[5rem] ${
                        isDark
                          ? "border-white/10 bg-black/30 text-white/90 placeholder:text-white/25"
                          : "border-[#141414]/15 bg-[#141414]/5 text-[#141414] placeholder:text-[#141414]/35"
                      }`}
                      disabled={rotationLoading}
                      autoComplete="off"
                      spellCheck={false}
                    />
                    <p className={`text-[10px] font-mono mt-2 ${muted}`}>
                      Expected prefix: {rotatingKey.prefix} · Min length: {rotatingKey.min_length}
                    </p>
                    {formatError && (
                      <p className="text-xs text-rose-400 mt-2 font-mono">{formatError}</p>
                    )}
                    {!formatError && newKeyValue.trim() !== "" && (
                      <p className="text-xs text-emerald-400 mt-2 font-mono flex items-center gap-1.5">
                        <CheckCircle className="w-3.5 h-3.5 shrink-0" />
                        Format valid
                      </p>
                    )}
                    <div className="flex flex-wrap items-center gap-3 mt-6">
                      <button
                        type="button"
                        onClick={closeRotationModal}
                        disabled={rotationLoading}
                        className={`rounded-xl border px-4 py-2 text-xs font-mono font-bold ${border} ${subtle} opacity-80 hover:opacity-100 disabled:opacity-40 disabled:cursor-not-allowed`}
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleRotate()}
                        disabled={
                          rotationLoading ||
                          !newKeyValue.trim() ||
                          Boolean(formatError) ||
                          Boolean(validateKeyFormat(rotatingKey, newKeyValue))
                        }
                        className="rounded-xl border border-amber-500/40 bg-amber-500/15 px-4 py-2 text-xs font-mono font-bold text-amber-200 hover:bg-amber-500/25 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        {rotationLoading ? (
                          <span className="inline-flex items-center gap-2">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            Testing key…
                          </span>
                        ) : (
                          "Rotate key"
                        )}
                      </button>
                    </div>
                    {rotationLoading && (
                      <p className={`text-[10px] font-mono ${muted} mt-3`}>
                        Testing key against provider…
                      </p>
                    )}
                  </>
                ) : (
                  <div className="space-y-4">
                    {rotationResult.status === "success" && (
                      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 space-y-2">
                        <div className="flex items-center gap-2 text-emerald-400 font-bold text-sm">
                          <CheckCircle className="w-5 h-5 shrink-0" />
                          Key rotated successfully
                        </div>
                        {rotationResult.old_key_health && (
                          <p className={`text-xs font-mono ${muted}`}>
                            Previous: {rotationResult.old_key_health}
                          </p>
                        )}
                        {rotationResult.new_key_health && (
                          <p className={`text-xs font-mono ${muted}`}>
                            New: {rotationResult.new_key_health}
                          </p>
                        )}
                      </div>
                    )}
                    {rotationResult.status === "rolled_back" && (
                      <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-2">
                        <div className="flex items-center gap-2 text-amber-300 font-bold text-sm">
                          <AlertTriangle className="w-5 h-5 shrink-0" />
                          Rotation rolled back — old key restored
                        </div>
                        {rotationResult.error && (
                          <p className="text-xs font-mono text-amber-200/90">{rotationResult.error}</p>
                        )}
                      </div>
                    )}
                    {rotationResult.status !== "success" && rotationResult.status !== "rolled_back" && (
                      <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 space-y-2">
                        <div className="flex items-center gap-2 text-rose-400 font-bold text-sm">
                          <XCircle className="w-5 h-5 shrink-0" />
                          Rotation failed
                        </div>
                        {rotationResult.error && (
                          <p className="text-xs font-mono text-rose-200/90">{rotationResult.error}</p>
                        )}
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={closeRotationModal}
                      className={`rounded-xl border px-4 py-2 text-xs font-mono font-bold ${border} ${subtle} w-full sm:w-auto`}
                    >
                      Close
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </motion.div>
      )}

      {activeTab === "Events" && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
          <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
            Recent auth & security events
          </p>
          {loadLogs ? (
            <SectionSkeleton border={border} subtle={subtle} />
          ) : errLogs ? (
            <SectionUnavailable border={border} subtle={subtle} />
          ) : logEntries.length === 0 ? (
            <div
              className={`rounded-2xl border ${border} ${subtle} p-10 flex flex-col items-center gap-3 text-center`}
            >
              <Shield className="w-10 h-10 text-emerald-400/60" />
              <p className={`text-sm font-mono ${muted}`}>No recent security events</p>
            </div>
          ) : (
            <div className={`rounded-2xl border ${border} ${subtle} overflow-hidden`}>
              <table className="w-full text-xs">
                <thead>
                  <tr className={isDark ? "bg-white/5" : "bg-black/5"}>
                    <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                      Timestamp
                    </th>
                    <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                      Level
                    </th>
                    <th className="text-left px-2 py-2 font-mono uppercase opacity-40">
                      Service
                    </th>
                    <th className="text-left px-4 py-2 font-mono uppercase opacity-40">
                      Message
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {logEntries.map((e, i) => {
                    const lv = (e.level || "").toUpperCase();
                    let badgeClass =
                      "border-zinc-500/30 bg-zinc-500/15 text-zinc-400";
                    if (lv === "WARNING") {
                      badgeClass = "border-amber-500/30 bg-amber-500/15 text-amber-400";
                    }
                    if (lv === "ERROR" || lv === "CRITICAL") {
                      badgeClass = "border-rose-500/30 bg-rose-500/15 text-rose-400";
                    }
                    const pulse = lv === "CRITICAL" ? " animate-pulse" : "";
                    return (
                      <tr key={`${e.ts}-${i}`}>
                        <td className="px-4 py-2 font-mono whitespace-nowrap opacity-70">
                          {e.ts || "—"}
                        </td>
                        <td className="px-2 py-2">
                          <span
                            className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${badgeClass}${pulse}`}
                          >
                            {e.level || "—"}
                          </span>
                        </td>
                        <td className="px-2 py-2 font-mono opacity-80">{e.service}</td>
                        <td className="px-4 py-2 font-mono opacity-90 break-all max-w-md">
                          {e.message}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </motion.div>
      )}
    </motion.div>
  );
}
