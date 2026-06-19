import { useState, useEffect, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import {
  Shield, Key, Globe, Radio, AlertTriangle,
  RotateCw, Bug, Plug, ShieldCheck, Archive, ShieldAlert, Activity,
  ChevronRight, Clock, Gauge, Play, RefreshCw, Search, Siren,
} from "lucide-react";
import { apiJson } from "../lib/apiFetch";
import { useAppStore } from "../store";
import type {
  JwtCheck, RlsStatus, ChildProfileStatus, Perimeter, CertRow,
  LogEntry, RotatableKey, RotationResult, SecretAuditEvent,
  SecretsAuditResponse, HoneypotData, McpRegistry, LogsQueryResponse,
  PorchlightResponse, PorchlightReport, AgentManualRunResponse, KeyturnerStatus,
  WardenStatus, SecurityAgentEvent, SecurityAgentEventsResponse,
} from "../types/security";
import {
  OverviewTab, IdentityTab, NetworkTab, SweepTab,
  KeysTab, WardenTab, LedgerTab, SentryTab, TradeGuardTab, PorchlightTab, HoneypotTab, McpTab, EventsTab,
  SecurityAgentsConsole, computePostureScore, scoreColor, C_SCORE,
} from "../components/security";

const TABS = ["Overview", "Identity", "Network", "Sweep", "Warden", "Sentry", "Trade Guard", "Ledger", "Keyturner", "Porchlight", "Tripwire", "MCP", "Events"] as const;
type TabId = (typeof TABS)[number];

const TAB_ICONS: Record<string, typeof Shield> = {
  Overview: Shield,
  Identity: Key,
  Network: Globe,
  Sweep: Radio,
  Warden: ShieldCheck,
  Sentry: ShieldAlert,
  "Trade Guard": Activity,
  Ledger: Archive,
  Keyturner: RotateCw,
  Porchlight: Shield,
  Tripwire: Bug,
  MCP: Plug,
  Events: AlertTriangle,
};

const REFRESH_MS = 30_000;
const AT0_MARK = new URL("../assets/logo/at0-symbol-color.svg", import.meta.url).href;

type SeverityLevel = "critical" | "high" | "medium" | "low" | "info";

interface CommandAction {
  id: string;
  title: string;
  detail: string;
  severity: SeverityLevel;
  owner: string;
  tab: TabId;
  cta?: string;
}

function normalizeSeverity(value: string | null | undefined): SeverityLevel {
  const normalized = (value ?? "info").toLowerCase();
  if (normalized === "critical" || normalized === "error" || normalized === "fail") return "critical";
  if (normalized === "high") return "high";
  if (normalized === "medium" || normalized === "warn" || normalized === "warning" || normalized === "needs_input") return "medium";
  if (normalized === "low") return "low";
  return "info";
}

function severityRank(value: SeverityLevel): number {
  if (value === "critical") return 5;
  if (value === "high") return 4;
  if (value === "medium") return 3;
  if (value === "low") return 2;
  return 1;
}

function severityClass(value: SeverityLevel, isDark: boolean): string {
  if (value === "critical" || value === "high") {
    return isDark
      ? "border-rose-400/35 bg-rose-500/15 text-rose-200"
      : "border-rose-500/35 bg-rose-50 text-rose-700";
  }
  if (value === "medium") {
    return isDark
      ? "border-amber-400/35 bg-amber-500/15 text-amber-200"
      : "border-amber-500/35 bg-amber-50 text-amber-800";
  }
  if (value === "low") {
    return isDark
      ? "border-sky-400/30 bg-sky-500/12 text-sky-200"
      : "border-sky-500/30 bg-sky-50 text-sky-800";
  }
  return isDark
    ? "border-emerald-400/30 bg-emerald-500/12 text-emerald-200"
    : "border-emerald-500/30 bg-emerald-50 text-emerald-800";
}

function tabForOwner(owner: string): TabId {
  const normalized = owner.toLowerCase();
  if (normalized.includes("porchlight")) return "Porchlight";
  if (normalized.includes("keyturner")) return "Keyturner";
  if (normalized.includes("sweep") || normalized.includes("network_watchdog")) return "Sweep";
  if (normalized.includes("tripwire") || normalized.includes("honeypot")) return "Tripwire";
  if (normalized.includes("sentry")) return "Sentry";
  if (normalized.includes("trade")) return "Trade Guard";
  if (normalized.includes("ledger")) return "Ledger";
  if (normalized.includes("warden")) return "Warden";
  return "Events";
}

function formatLabel(value: string | null | undefined): string {
  if (!value) return "unknown";
  return value.replaceAll("_", " ");
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
  const [agentEvents, setAgentEvents] = useState<SecurityAgentEvent[]>([]);

  const [loadJwt, setLoadJwt] = useState(true);
  const [loadRls, setLoadRls] = useState(true);
  const [loadChild, setLoadChild] = useState(true);
  const [loadPerimeter, setLoadPerimeter] = useState(true);
  const [loadCerts, setLoadCerts] = useState(true);
  const [loadLogs, setLoadLogs] = useState(true);
  const [loadAgentEvents, setLoadAgentEvents] = useState(true);

  const [errJwt, setErrJwt] = useState(false);
  const [errRls, setErrRls] = useState(false);
  const [errChild, setErrChild] = useState(false);
  const [errPerimeter, setErrPerimeter] = useState(false);
  const [errCerts, setErrCerts] = useState(false);
  const [errLogs, setErrLogs] = useState(false);
  const [errAgentEvents, setErrAgentEvents] = useState(false);

  const [rotatableKeys, setRotatableKeys] = useState<RotatableKey[]>([]);
  const [secretsAuditEvents, setSecretsAuditEvents] = useState<SecretAuditEvent[]>([]);
  const [loadRotatableKeys, setLoadRotatableKeys] = useState(true);
  const [loadSecretsAudit, setLoadSecretsAudit] = useState(true);
  const [errRotatableKeys, setErrRotatableKeys] = useState(false);
  const [errSecretsAudit, setErrSecretsAudit] = useState(false);
  const [keyturnerStatus, setKeyturnerStatus] = useState<KeyturnerStatus | null>(null);
  const [loadKeyturner, setLoadKeyturner] = useState(true);
  const [errKeyturner, setErrKeyturner] = useState(false);
  const [wardenStatus, setWardenStatus] = useState<WardenStatus | null>(null);
  const [loadWarden, setLoadWarden] = useState(true);
  const [errWarden, setErrWarden] = useState(false);

  const [rotatingKey, setRotatingKey] = useState<RotatableKey | null>(null);
  const [newKeyValue, setNewKeyValue] = useState("");
  const [rotationLoading, setRotationLoading] = useState(false);
  const [rotationResult, setRotationResult] = useState<RotationResult | null>(null);
  const [formatError, setFormatError] = useState<string | null>(null);

  const [honeypotData, setHoneypotData] = useState<HoneypotData | null>(null);
  const [mcpRegistry, setMcpRegistry] = useState<McpRegistry | null>(null);
  const [loadHoneypot, setLoadHoneypot] = useState(true);
  const [loadMcp, setLoadMcp] = useState(true);
  const [errHoneypot, setErrHoneypot] = useState(false);
  const [errMcp, setErrMcp] = useState(false);

  const [porchlightReport, setPorchlightReport] = useState<PorchlightReport | null>(null);
  const [loadPorchlight, setLoadPorchlight] = useState(true);
  const [errPorchlight, setErrPorchlight] = useState(false);
  const [runPorchlightLoading, setRunPorchlightLoading] = useState(false);
  const [runPorchlightError, setRunPorchlightError] = useState<string | null>(null);
  const [runSweepLoading, setRunSweepLoading] = useState(false);
  const [runSweepError, setRunSweepError] = useState<string | null>(null);

  const mounted = useRef(true);
  const fetchRunning = useRef(false);

  const fetchAll = useCallback(async (showLoading: boolean) => {
    if (!mounted.current || fetchRunning.current) return;
    fetchRunning.current = true;

    if (showLoading) {
      setLoadJwt(true); setLoadRls(true); setLoadChild(true);
      setLoadPerimeter(true); setLoadCerts(true); setLoadLogs(true); setLoadAgentEvents(true);
      setLoadRotatableKeys(true); setLoadSecretsAudit(true); setLoadKeyturner(true); setLoadWarden(true);
      setLoadHoneypot(true); setLoadMcp(true); setLoadPorchlight(true);
    }

    try {
      const [j, r, c, p, cert, logs, agentEventsResult, rk, sa, kt, warden, hp, mcp, porch] = await Promise.all([
        apiJson<JwtCheck>("/v1/security/jwt-check").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<RlsStatus>("/v1/security/rls-status").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<ChildProfileStatus>("/v1/security/child-profiles").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<Perimeter>("/v1/security/perimeter").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<CertRow[]>("/v1/mesh/certs").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<LogsQueryResponse>("/v1/logs/query?limit=20&level=WARNING&service=alpha_brain").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<SecurityAgentEventsResponse>("/v1/security/agent-events?limit=25").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<{ keys: RotatableKey[] }>("/v1/security/rotatable-keys").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const, data: { keys: [] as RotatableKey[] } })),
        apiJson<SecretsAuditResponse>("/v1/security/secrets-audit?limit=20").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<KeyturnerStatus>("/v1/security/keyturner-status").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<WardenStatus>("/v1/security/warden-status").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<HoneypotData>("/v1/honeypot/events?limit=50").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<McpRegistry>("/v1/security/mcp/registry").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<PorchlightResponse>("/v1/security/porchlight").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
      ]);

      if (!mounted.current) return;

      if (j.ok) { setJwt(j.data); setErrJwt(false); } else { setJwt(null); setErrJwt(true); }
      if (r.ok) { setRls(r.data); setErrRls(false); } else { setRls(null); setErrRls(true); }
      if (c.ok) { setChild(c.data); setErrChild(false); } else { setChild(null); setErrChild(true); }
      if (p.ok) { setPerimeter(p.data); setErrPerimeter(false); } else { setPerimeter(null); setErrPerimeter(true); }
      if (cert.ok) { setCerts(cert.data); setErrCerts(false); } else { setCerts(null); setErrCerts(true); }
      if (logs.ok) {
        const data = logs.data;
        if (data.status !== "error") { setLogEntries(data.entries ?? []); setErrLogs(false); }
        else { setLogEntries([]); setErrLogs(true); }
      } else { setLogEntries([]); setErrLogs(true); }
      if (agentEventsResult.ok) { setAgentEvents(agentEventsResult.data.events ?? []); setErrAgentEvents(false); }
      else { setAgentEvents([]); setErrAgentEvents(true); }
      if (rk.ok) { setRotatableKeys(rk.data.keys ?? []); setErrRotatableKeys(false); }
      else { setRotatableKeys([]); setErrRotatableKeys(true); }
      if (sa.ok) { setSecretsAuditEvents(sa.data.events ?? []); setErrSecretsAudit(Boolean(sa.data.error)); }
      else { setSecretsAuditEvents([]); setErrSecretsAudit(true); }
      if (kt.ok) { setKeyturnerStatus(kt.data); setErrKeyturner(false); } else { setKeyturnerStatus(null); setErrKeyturner(true); }
      if (warden.ok) { setWardenStatus(warden.data); setErrWarden(false); } else { setWardenStatus(null); setErrWarden(true); }
      if (hp.ok) { setHoneypotData(hp.data); setErrHoneypot(false); } else { setHoneypotData(null); setErrHoneypot(true); }
      if (mcp.ok) { setMcpRegistry(mcp.data); setErrMcp(false); } else { setMcpRegistry(null); setErrMcp(true); }
      if (porch.ok) { setPorchlightReport(porch.data.report); setErrPorchlight(false); } else { setPorchlightReport(null); setErrPorchlight(true); }
    } finally {
      fetchRunning.current = false;
      if (mounted.current && showLoading) {
        setLoadJwt(false); setLoadRls(false); setLoadChild(false);
        setLoadPerimeter(false); setLoadCerts(false); setLoadLogs(false); setLoadAgentEvents(false);
        setLoadRotatableKeys(false); setLoadSecretsAudit(false); setLoadKeyturner(false); setLoadWarden(false);
        setLoadHoneypot(false); setLoadMcp(false); setLoadPorchlight(false);
      }
    }
  }, []);

  const closeRotationModal = useCallback(() => {
    setRotatingKey(null); setNewKeyValue(""); setFormatError(null);
    setRotationResult(null); setRotationLoading(false);
  }, []);

  const handleRunPorchlight = useCallback(async () => {
    setRunPorchlightLoading(true);
    setRunPorchlightError(null);
    try {
      const result = await apiJson<AgentManualRunResponse>("/v1/agents/porchlight/run", { method: "POST" });
      if (!result.executed) {
        setRunPorchlightError(result.skipped_reason ?? result.error_text ?? "Porchlight did not run");
      }
      await fetchAll(false);
    } catch (e) {
      setRunPorchlightError(e instanceof Error ? e.message : "Porchlight run failed");
    } finally {
      setRunPorchlightLoading(false);
    }
  }, [fetchAll]);

  const handleRunSweep = useCallback(async () => {
    setRunSweepLoading(true);
    setRunSweepError(null);
    try {
      const result = await apiJson<AgentManualRunResponse>("/v1/agents/sweep/run", { method: "POST" });
      if (!result.executed) {
        setRunSweepError(result.skipped_reason ?? result.error_text ?? "Sweep did not run");
      }
      await fetchAll(false);
    } catch (e) {
      setRunSweepError(e instanceof Error ? e.message : "Sweep run failed");
    } finally {
      setRunSweepLoading(false);
    }
  }, [fetchAll]);

  const handleRotate = useCallback(async () => {
    if (!rotatingKey || !newKeyValue) return;
    setRotationLoading(true); setRotationResult(null);
    try {
      const result = await apiJson<RotationResult>("/v1/security/rotate-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key_name: rotatingKey.key_name, new_value: newKeyValue }),
      });
      setRotationResult(result);
      if (result.status === "success") setNewKeyValue("");
    } catch (e) {
      setRotationResult({
        status: "error", rotation_id: "", key_name: rotatingKey.key_name,
        error: e instanceof Error ? e.message : "Rotation failed",
        old_key_health: null, new_key_health: null,
      });
    } finally { setRotationLoading(false); }
  }, [rotatingKey, newKeyValue]);

  useEffect(() => {
    mounted.current = true;
    void fetchAll(true);
    const id = setInterval(() => void fetchAll(false), REFRESH_MS);
    return () => { mounted.current = false; clearInterval(id); };
  }, [fetchAll]);

  /* Computed values for overview */
  const honeypotTotalHits = honeypotData !== null && !errHoneypot ? honeypotData.total : null;
  const fallbackScore = computePostureScore(jwt, rls, child, perimeter, certs, honeypotTotalHits);
  const postureScore = wardenStatus?.posture_score;
  const displayScore = postureScore?.score ?? fallbackScore.displayScore;
  const reserved = postureScore?.reserved ?? fallbackScore.reserved;
  const strokeColor = scoreColor(displayScore, isDark);
  const dashEarned = (displayScore / 100) * C_SCORE;
  const checksPassing = postureScore?.controls_passing
    ?? (jwt?.passing ?? 0) + (perimeter?.ports.filter((p) => p.reachable === p.expected).length ?? 0);
  const checksTotal = postureScore?.controls_total
    ?? (jwt?.total ?? 0) + (perimeter?.ports.length ?? 0);
  const shortestCertDays = certs && certs.length ? Math.min(...certs.map((c) => c.days_remaining)) : null;
  const sortedCerts = certs ? [...certs].sort((a, b) => a.days_remaining - b.days_remaining) : [];
  const protectedTables = rls?.tables.filter((t) => t.protected ?? t.rls === "enabled") ?? [];
  const unprotectedTables = rls?.tables.filter((t) => !(t.protected ?? t.rls === "enabled")) ?? [];
  const nodeOrder = ["brain", "gateway", "endpoint", "sandbox"];
  const portsByNode = perimeter
    ? [...perimeter.ports].sort((a, b) => nodeOrder.indexOf(a.node) - nodeOrder.indexOf(b.node) || a.port - b.port)
    : [];
  const topPostureGaps = postureScore?.top_gaps ?? [];
  const ownerRoutes = wardenStatus?.owner_routes ?? [];
  const attentionAgents = wardenStatus?.agents.filter((agent) => agent.needs_attention) ?? [];
  const failingPorchlightChecks = porchlightReport?.checks
    .filter((check) => check.status !== "pass")
    .sort((a, b) => severityRank(normalizeSeverity(b.severity)) - severityRank(normalizeSeverity(a.severity))) ?? [];
  const severeEvents = agentEvents
    .filter((event) => severityRank(normalizeSeverity(event.severity)) >= severityRank("medium"))
    .slice(0, 4);
  const certsInsideWindow = sortedCerts.filter((cert) => cert.days_remaining <= 30);
  const keyturnerAttention = keyturnerStatus?.counts.attention ?? 0;
  const tradeGuardEvidence = wardenStatus?.trade_guard_financial_evidence;
  const tradeGuardNeedsAttention = tradeGuardEvidence?.status === "warn" || tradeGuardEvidence?.status === "fail";

  const commandActions: CommandAction[] = [
    ...ownerRoutes.slice(0, 4).map((route) => ({
      id: `route-${route.ticket_key}`,
      title: route.title,
      detail: route.detail || formatLabel(route.recommended_action),
      severity: normalizeSeverity(route.severity),
      owner: formatLabel(route.owner_agent),
      tab: tabForOwner(route.owner_agent),
      cta: route.approval_required ? "Review approval path" : "Open owner route",
    })),
    ...topPostureGaps.slice(0, 3).map((gap) => ({
      id: `gap-${gap.id}`,
      title: gap.title,
      detail: gap.summary,
      severity: normalizeSeverity(gap.status),
      owner: formatLabel(gap.owner_agent),
      tab: tabForOwner(gap.owner_agent),
      cta: "Open control gap",
    })),
    ...failingPorchlightChecks.slice(0, 3).map((check) => ({
      id: `porchlight-${check.name}`,
      title: check.summary,
      detail: check.detail || formatLabel(check.name),
      severity: normalizeSeverity(check.severity),
      owner: "Porchlight",
      tab: "Porchlight" as TabId,
      cta: "Open check",
    })),
    ...severeEvents.map((event) => ({
      id: `event-${event.id}`,
      title: event.title,
      detail: event.message,
      severity: normalizeSeverity(event.severity),
      owner: formatLabel(event.agent_id),
      tab: tabForOwner(event.agent_id),
      cta: "Open event context",
    })),
    ...(keyturnerAttention > 0 ? [{
      id: "keyturner-attention",
      title: "Key rotation attention",
      detail: `${keyturnerAttention} managed secret${keyturnerAttention === 1 ? "" : "s"} need review.`,
      severity: "medium" as SeverityLevel,
      owner: "Keyturner",
      tab: "Keyturner" as TabId,
      cta: "Open rotation ledger",
    }] : []),
    ...(certsInsideWindow.length > 0 ? [{
      id: "sweep-cert-window",
      title: "TLS renewal window",
      detail: `${certsInsideWindow.length} node certificate${certsInsideWindow.length === 1 ? "" : "s"} inside 30 days.`,
      severity: certsInsideWindow.some((cert) => cert.days_remaining <= 14) ? "medium" as SeverityLevel : "low" as SeverityLevel,
      owner: "Sweep",
      tab: "Sweep" as TabId,
      cta: "Open TLS evidence",
    }] : []),
    ...(tradeGuardNeedsAttention ? [{
      id: "trade-guard-financial-evidence",
      title: "Trade Guard evidence",
      detail: tradeGuardEvidence?.summary ?? "Financial posture requires review.",
      severity: normalizeSeverity(tradeGuardEvidence?.status),
      owner: "Trade Guard",
      tab: "Trade Guard" as TabId,
      cta: "Open money-path controls",
    }] : []),
  ]
    .sort((a, b) => severityRank(b.severity) - severityRank(a.severity))
    .filter((action, index, actions) => actions.findIndex((candidate) => candidate.id === action.id) === index)
    .slice(0, 6);

  const tabAlerts: Partial<Record<TabId, number>> = {
    Identity: (jwt?.failing ?? 0) + unprotectedTables.length + (child?.overall && child.overall !== "pass" ? 1 : 0),
    Network: perimeter?.ports.filter((port) => port.reachable !== port.expected).length ?? 0,
    Sweep: certsInsideWindow.length,
    Warden: wardenStatus?.counts.attention ?? topPostureGaps.length,
    Sentry: attentionAgents.filter((agent) => agent.agent_id === "sentry").length,
    "Trade Guard": tradeGuardNeedsAttention ? 1 : 0,
    Ledger: attentionAgents.filter((agent) => agent.agent_id === "ledger").length,
    Keyturner: keyturnerAttention,
    Porchlight: failingPorchlightChecks.length,
    Tripwire: honeypotData?.hits_24h ?? honeypotData?.total ?? 0,
    MCP: mcpRegistry ? mcpRegistry.total - mcpRegistry.active : 0,
    Events: severeEvents.length,
  };
  const commandSeverity = commandActions[0]?.severity ?? "info";
  const commandStatus = commandActions.length > 0 ? "Attention needed" : "No immediate action";

  const theme_props = { isDark, border, subtle, fg, muted };

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="max-w-7xl space-y-6">
      <section className={`relative overflow-hidden rounded-2xl border ${border} ${isDark ? "bg-[#080808]" : "bg-[#f8f6f0]"} p-5 shadow-sm`}>
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-[#ff6a00] via-[#f5c542] to-[#00c2a8]" />
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <div className={`flex h-11 w-11 items-center justify-center rounded-xl border ${border} ${isDark ? "bg-white/10" : "bg-white/80"}`}>
                <img src={AT0_MARK} alt="AT0" className="h-6 w-6" />
              </div>
              <div>
                <p className={`text-[10px] font-mono uppercase tracking-[0.24em] ${muted}`}>AT0 security command</p>
                <h1 className={`mt-1 text-3xl font-semibold tracking-tight ${fg}`}>Security</h1>
              </div>
            </div>
            <p className={`mt-4 max-w-3xl text-sm leading-6 ${muted}`}>
              Warden-owned posture, agent events, identity, perimeter, TLS, and money-path guardrails in one operating surface.
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <span className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-mono ${severityClass(commandSeverity, isDark)}`}>
                <Siren className="h-3.5 w-3.5" />
                {commandStatus}
              </span>
              <span className={`inline-flex items-center gap-2 rounded-full border ${border} px-3 py-1.5 text-xs font-mono ${muted}`}>
                <Clock className="h-3.5 w-3.5" />
                Auto refresh 30s
              </span>
              <span className={`inline-flex items-center gap-2 rounded-full border ${border} px-3 py-1.5 text-xs font-mono ${muted}`}>
                <Search className="h-3.5 w-3.5" />
                Drill down by owner
              </span>
            </div>
          </div>

          <div className="grid min-w-0 grid-cols-2 gap-3 sm:min-w-[390px]">
            <button
              type="button"
              onClick={() => setActiveTab("Warden")}
              className={`col-span-2 rounded-xl border ${border} ${isDark ? "bg-white/5 hover:bg-white/10" : "bg-white/80 hover:bg-white"} p-4 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-orange-400/40`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>Posture score</p>
                  <p className="mt-2 flex items-end gap-2 font-mono">
                    <span className="text-4xl font-bold tabular-nums" style={{ color: strokeColor }}>{displayScore}</span>
                    <span className={`pb-1 text-xs ${muted}`}>/100</span>
                  </p>
                </div>
                <Gauge className="h-5 w-5" style={{ color: strokeColor }} />
              </div>
              <p className={`mt-2 text-xs font-mono ${muted}`}>
                {checksTotal > 0 ? `${checksPassing}/${checksTotal} controls passing` : "Collecting posture data"}
              </p>
            </button>

            <button
              type="button"
              onClick={() => void handleRunPorchlight()}
              disabled={runPorchlightLoading}
              className={`rounded-xl border ${border} ${isDark ? "bg-white/5 hover:bg-white/10" : "bg-white/80 hover:bg-white"} p-4 text-left transition-colors disabled:cursor-wait disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-orange-400/40`}
            >
              <Play className="h-4 w-4 text-orange-400" />
              <p className={`mt-3 text-sm font-bold ${fg}`}>{runPorchlightLoading ? "Running" : "Run Porchlight"}</p>
              <p className={`mt-1 text-[10px] font-mono uppercase ${muted}`}>posture sweep</p>
            </button>

            <button
              type="button"
              onClick={() => void handleRunSweep()}
              disabled={runSweepLoading}
              className={`rounded-xl border ${border} ${isDark ? "bg-white/5 hover:bg-white/10" : "bg-white/80 hover:bg-white"} p-4 text-left transition-colors disabled:cursor-wait disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-orange-400/40`}
            >
              <Radio className="h-4 w-4 text-sky-400" />
              <p className={`mt-3 text-sm font-bold ${fg}`}>{runSweepLoading ? "Running" : "Run Sweep"}</p>
              <p className={`mt-1 text-[10px] font-mono uppercase ${muted}`}>network and TLS</p>
            </button>
          </div>
        </div>

        {(runPorchlightError || runSweepError) && (
          <div className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
            {runPorchlightError && (
              <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                Porchlight: {runPorchlightError}
              </div>
            )}
            {runSweepError && (
              <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                Sweep: {runSweepError}
              </div>
            )}
          </div>
        )}
      </section>

      <SecurityAgentsConsole
        {...theme_props}
        wardenStatus={wardenStatus}
        porchlightReport={porchlightReport}
        agentEvents={agentEvents}
        loadWarden={loadWarden}
        loadPorchlight={loadPorchlight}
        errWarden={errWarden}
        errPorchlight={errPorchlight}
        onSelectTab={(tab) => setActiveTab(tab as TabId)}
      />

      <section>
        <div className={`rounded-2xl border ${border} ${subtle} p-4`}>
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className={`text-[10px] font-mono uppercase tracking-widest ${muted}`}>Action queue</p>
              <p className={`mt-1 text-sm ${muted}`}>Highest-signal issues with owner routing and direct drill-down.</p>
            </div>
            <button
              type="button"
              onClick={() => void fetchAll(false)}
              className={`inline-flex h-10 items-center gap-2 rounded-lg border ${border} px-3 text-xs font-mono ${muted} transition-colors hover:opacity-80 focus:outline-none focus:ring-2 focus:ring-orange-400/40`}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
          </div>
          {commandActions.length > 0 ? (
            <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
              {commandActions.map((action) => (
                <button
                  key={action.id}
                  type="button"
                  onClick={() => setActiveTab(action.tab)}
                  className={`group rounded-xl border ${border} ${isDark ? "bg-white/5 hover:bg-white/10" : "bg-white/70 hover:bg-white"} p-4 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-orange-400/40`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <span className={`inline-flex rounded-md border px-2 py-1 text-[10px] font-mono uppercase ${severityClass(action.severity, isDark)}`}>
                        {action.severity}
                      </span>
                      <p className={`mt-3 text-sm font-bold ${fg}`}>{action.title}</p>
                      <p className={`mt-1 line-clamp-2 text-xs leading-5 ${muted}`}>{action.detail}</p>
                    </div>
                    <ChevronRight className={`mt-1 h-4 w-4 shrink-0 ${muted} transition-transform group-hover:translate-x-0.5`} />
                  </div>
                  <div className={`mt-4 flex items-center justify-between gap-3 text-[10px] font-mono uppercase ${muted}`}>
                    <span>Owner: {action.owner}</span>
                    <span>{action.cta ?? "Open"}</span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setActiveTab("Overview")}
              className={`mt-4 w-full rounded-xl border p-5 text-left transition-opacity hover:opacity-90 ${
                isDark
                  ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
                  : "border-emerald-500/35 bg-emerald-50 text-emerald-900"
              }`}
            >
              <ShieldCheck className="h-5 w-5" />
              <p className="mt-3 text-sm font-bold">No active security actions.</p>
              <p className="mt-1 text-xs opacity-80">Use the tabs below for posture evidence and historical events.</p>
            </button>
          )}
        </div>
      </section>

      {/* sub-tab pills */}
      <div className={`sticky top-0 z-10 -mx-2 overflow-x-auto border-y ${border} ${isDark ? "bg-[#080808]/90" : "bg-[#f8f6f0]/90"} px-2 py-3 backdrop-blur`}>
        <div className="flex min-w-max gap-2">
        {TABS.map((tab) => {
          const Icon = TAB_ICONS[tab];
          const active = activeTab === tab;
          const alertCount = tabAlerts[tab] ?? 0;
          return (
            <button
              key={tab} type="button" onClick={() => setActiveTab(tab)}
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-mono transition-colors focus:outline-none focus:ring-2 focus:ring-orange-400/40 ${border} ${
                active
                  ? isDark ? "bg-white/10 font-bold text-white" : "bg-[#141414]/10 font-bold text-[#141414]"
                  : `${subtle} opacity-60 hover:opacity-90`
              }`}
            >
              <Icon className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
              {tab}
              {alertCount > 0 && (
                <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold ${active ? "bg-orange-500 text-black" : "bg-orange-500/20 text-orange-400"}`}>
                  {alertCount > 99 ? "99+" : alertCount}
                </span>
              )}
            </button>
          );
        })}
        </div>
      </div>

      {activeTab === "Overview" && (
        <OverviewTab
          {...theme_props}
          jwt={jwt} rls={rls} perimeter={perimeter} certs={certs} honeypotData={honeypotData}
          loadJwt={loadJwt} loadRls={loadRls} loadPerimeter={loadPerimeter}
          loadCerts={loadCerts} loadChild={loadChild} loadHoneypot={loadHoneypot}
          errJwt={errJwt} errRls={errRls} errPerimeter={errPerimeter}
          errCerts={errCerts} errHoneypot={errHoneypot}
          displayScore={displayScore} reserved={reserved}
          dashEarned={dashEarned} strokeColor={strokeColor}
          checksPassing={checksPassing} checksTotal={checksTotal}
          shortestCertDays={shortestCertDays}
          postureScore={postureScore}
          setActiveTab={setActiveTab as (tab: string) => void}
        />
      )}

      {activeTab === "Identity" && (
        <IdentityTab
          {...theme_props}
          jwt={jwt} rls={rls} child={child}
          protectedTables={protectedTables} unprotectedTables={unprotectedTables}
          loadJwt={loadJwt} loadRls={loadRls} loadChild={loadChild}
          errJwt={errJwt} errRls={errRls} errChild={errChild}
        />
      )}

      {activeTab === "Network" && (
        <NetworkTab
          {...theme_props}
          perimeter={perimeter} portsByNode={portsByNode}
          loadPerimeter={loadPerimeter} errPerimeter={errPerimeter}
        />
      )}

      {activeTab === "Sweep" && (
        <SweepTab
          {...theme_props}
          certs={certs} sortedCerts={sortedCerts} loadCerts={loadCerts} errCerts={errCerts}
          wardenStatus={wardenStatus} loadWarden={loadWarden} errWarden={errWarden}
          runLoading={runSweepLoading} runError={runSweepError}
          onRun={() => void handleRunSweep()}
        />
      )}

      {activeTab === "Warden" && (
        <WardenTab
          {...theme_props}
          wardenStatus={wardenStatus}
          loadWarden={loadWarden}
          errWarden={errWarden}
        />
      )}

      {activeTab === "Ledger" && (
        <LedgerTab
          {...theme_props}
          wardenStatus={wardenStatus}
          loadWarden={loadWarden}
          errWarden={errWarden}
        />
      )}

      {activeTab === "Sentry" && (
        <SentryTab
          {...theme_props}
          wardenStatus={wardenStatus}
          loadWarden={loadWarden}
          errWarden={errWarden}
          agentEvents={agentEvents}
          loadAgentEvents={loadAgentEvents}
          errAgentEvents={errAgentEvents}
        />
      )}

      {activeTab === "Trade Guard" && (
        <TradeGuardTab
          {...theme_props}
          wardenStatus={wardenStatus}
          loadWarden={loadWarden}
          errWarden={errWarden}
          agentEvents={agentEvents}
          loadAgentEvents={loadAgentEvents}
          errAgentEvents={errAgentEvents}
        />
      )}

      {activeTab === "Keyturner" && (
        <KeysTab
          {...theme_props}
          rotatableKeys={rotatableKeys} secretsAuditEvents={secretsAuditEvents}
          keyturnerStatus={keyturnerStatus}
          loadRotatableKeys={loadRotatableKeys} loadSecretsAudit={loadSecretsAudit}
          loadKeyturner={loadKeyturner}
          errRotatableKeys={errRotatableKeys} errSecretsAudit={errSecretsAudit}
          errKeyturner={errKeyturner}
          rotatingKey={rotatingKey} newKeyValue={newKeyValue}
          rotationLoading={rotationLoading} rotationResult={rotationResult} formatError={formatError}
          setRotatingKey={setRotatingKey} setNewKeyValue={setNewKeyValue}
          setFormatError={setFormatError} setRotationResult={setRotationResult}
          closeRotationModal={closeRotationModal} handleRotate={handleRotate}
        />
      )}

      {activeTab === "Porchlight" && (
        <PorchlightTab
          {...theme_props}
          report={porchlightReport}
          loadPorchlight={loadPorchlight}
          errPorchlight={errPorchlight}
          runLoading={runPorchlightLoading}
          runError={runPorchlightError}
          onRun={() => void handleRunPorchlight()}
        />
      )}

      {activeTab === "Tripwire" && (
        <HoneypotTab {...theme_props} honeypotData={honeypotData} loadHoneypot={loadHoneypot} errHoneypot={errHoneypot} />
      )}

      {activeTab === "MCP" && (
        <McpTab {...theme_props} mcpRegistry={mcpRegistry} loadMcp={loadMcp} errMcp={errMcp} />
      )}

      {activeTab === "Events" && (
        <EventsTab
          {...theme_props}
          agentEvents={agentEvents}
          loadAgentEvents={loadAgentEvents}
          errAgentEvents={errAgentEvents}
          logEntries={logEntries}
          loadLogs={loadLogs}
          errLogs={errLogs}
        />
      )}
    </motion.div>
  );
}
