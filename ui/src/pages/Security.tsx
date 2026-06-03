import { useState, useEffect, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import {
  Shield, Key, Globe, Lock, AlertTriangle,
  RotateCw, Bug, Plug, ShieldCheck,
} from "lucide-react";
import { apiJson } from "../lib/apiFetch";
import { useAppStore } from "../store";
import type {
  JwtCheck, RlsStatus, ChildProfileStatus, Perimeter, CertRow,
  LogEntry, RotatableKey, RotationResult, SecretAuditEvent,
  SecretsAuditResponse, HoneypotData, McpRegistry, LogsQueryResponse,
  PorchlightResponse, PorchlightReport, AgentManualRunResponse, KeyturnerStatus,
  WardenStatus,
} from "../types/security";
import {
  OverviewTab, IdentityTab, NetworkTab, CertsTab,
  KeysTab, WardenTab, PorchlightTab, HoneypotTab, McpTab, EventsTab,
  computePostureScore, scoreColor, C_SCORE,
} from "../components/security";

const TABS = ["Overview", "Identity", "Network", "Certs", "Warden", "Keys", "Porchlight", "Honeypot", "MCP", "Events"] as const;
type TabId = (typeof TABS)[number];

const TAB_ICONS: Record<string, typeof Shield> = {
  Overview: Shield,
  Identity: Key,
  Network: Globe,
  Certs: Lock,
  Warden: ShieldCheck,
  Keys: RotateCw,
  Porchlight: Shield,
  Honeypot: Bug,
  MCP: Plug,
  Events: AlertTriangle,
};

const REFRESH_MS = 30_000;

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

  const mounted = useRef(true);
  const fetchRunning = useRef(false);

  const fetchAll = useCallback(async (showLoading: boolean) => {
    if (!mounted.current || fetchRunning.current) return;
    fetchRunning.current = true;

    if (showLoading) {
      setLoadJwt(true); setLoadRls(true); setLoadChild(true);
      setLoadPerimeter(true); setLoadCerts(true); setLoadLogs(true);
      setLoadRotatableKeys(true); setLoadSecretsAudit(true); setLoadKeyturner(true); setLoadWarden(true);
      setLoadHoneypot(true); setLoadMcp(true); setLoadPorchlight(true);
    }

    try {
      const [j, r, c, p, cert, logs, rk, sa, kt, warden, hp, mcp, porch] = await Promise.all([
        apiJson<JwtCheck>("/v1/security/jwt-check").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<RlsStatus>("/v1/security/rls-status").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<ChildProfileStatus>("/v1/security/child-profiles").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<Perimeter>("/v1/security/perimeter").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<CertRow[]>("/v1/mesh/certs").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
        apiJson<LogsQueryResponse>("/v1/logs/query?limit=20&level=WARNING&service=alpha_brain").then((data) => ({ ok: true as const, data })).catch(() => ({ ok: false as const })),
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
        setLoadPerimeter(false); setLoadCerts(false); setLoadLogs(false);
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
  const { earned, displayScore, reserved } = computePostureScore(jwt, rls, child, perimeter, certs, honeypotTotalHits);
  const strokeColor = scoreColor(displayScore, isDark);
  const dashEarned = (earned / 100) * C_SCORE;
  const checksPassing = (jwt?.passing ?? 0) + (perimeter?.ports.filter((p) => p.reachable === p.expected).length ?? 0);
  const checksTotal = (jwt?.total ?? 0) + (perimeter?.ports.length ?? 0);
  const shortestCertDays = certs && certs.length ? Math.min(...certs.map((c) => c.days_remaining)) : null;
  const sortedCerts = certs ? [...certs].sort((a, b) => a.days_remaining - b.days_remaining) : [];
  const protectedTables = rls?.tables.filter((t) => t.protected ?? t.rls === "enabled") ?? [];
  const unprotectedTables = rls?.tables.filter((t) => !(t.protected ?? t.rls === "enabled")) ?? [];
  const nodeOrder = ["brain", "gateway", "endpoint", "sandbox"];
  const portsByNode = perimeter
    ? [...perimeter.ports].sort((a, b) => nodeOrder.indexOf(a.node) - nodeOrder.indexOf(b.node) || a.port - b.port)
    : [];

  const theme_props = { isDark, border, subtle, fg, muted };

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-6 max-w-5xl">
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
              key={tab} type="button" onClick={() => setActiveTab(tab)}
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-mono transition-colors ${border} ${
                active
                  ? isDark ? "bg-white/10 font-bold text-white" : "bg-black/10 font-bold text-[#141414]"
                  : `${subtle} opacity-60 hover:opacity-90`
              }`}
            >
              <Icon className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
              {tab}
            </button>
          );
        })}
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

      {activeTab === "Certs" && (
        <CertsTab
          {...theme_props}
          certs={certs} sortedCerts={sortedCerts} loadCerts={loadCerts} errCerts={errCerts}
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

      {activeTab === "Keys" && (
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

      {activeTab === "Honeypot" && (
        <HoneypotTab {...theme_props} honeypotData={honeypotData} loadHoneypot={loadHoneypot} errHoneypot={errHoneypot} />
      )}

      {activeTab === "MCP" && (
        <McpTab {...theme_props} mcpRegistry={mcpRegistry} loadMcp={loadMcp} errMcp={errMcp} />
      )}

      {activeTab === "Events" && (
        <EventsTab {...theme_props} logEntries={logEntries} loadLogs={loadLogs} errLogs={errLogs} />
      )}
    </motion.div>
  );
}
