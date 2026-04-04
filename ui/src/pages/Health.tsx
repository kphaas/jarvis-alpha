import { useEffect, useState, useCallback } from "react";
import type { ReactNode } from "react";
import { Cpu, Globe, Monitor, FlaskConical } from 'lucide-react';
import { apiFetch, apiJson } from "../lib/apiFetch";

const REFRESH_MS = 60_000;

interface NodeSummary {
  reachable: boolean;
  latency_ms: number | null;
}

interface HomeSummary {
  nodes: {
    brain: NodeSummary;
    gateway: NodeSummary;
    endpoint: NodeSummary;
  };
  costs_today_usd: number | null;
  cert_days_remaining: number | null;
  last_overnight_run: { status: string; ran_at: string } | null;
  cached_at: string;
}

interface MeshStatusPayload {
  checked_at: string;
  nodes: Array<{
    name: string;
    display_name: string;
    tailscale_ip: string | null;
    status: string;
    extra?: { response_time_ms?: number };
  }>;
}

interface LaunchAgentRow {
  label: string;
  pid: number | null;
  exit_code: number | null;
  status: string;
}

function agentShortLabel(label: string): string {
  return label.replace(/^com\.jarvis\./, "");
}

function agentBadgeColors(
  status: string,
  isDark: boolean
): { bg: string; fg: string } {
  const greyFg = isDark ? "#9ca3af" : "#64748b";
  const greyBg = isDark ? "rgba(107,114,128,0.25)" : "rgba(148,163,184,0.35)";
  switch (status) {
    case "running":
      return { bg: "rgba(34,197,94,0.2)", fg: "#22c55e" };
    case "idle":
      return { bg: "rgba(245,158,11,0.2)", fg: "#f59e0b" };
    case "error":
      return { bg: "rgba(239,68,68,0.2)", fg: "#ef4444" };
    case "not_found":
      return { bg: greyBg, fg: greyFg };
    default:
      return { bg: greyBg, fg: greyFg };
  }
}

function meshRowToNodeSummary(
  row: { status: string; extra?: { response_time_ms?: number } } | undefined
): NodeSummary {
  if (!row) return { reachable: false, latency_ms: null };
  const s = row.status.toLowerCase();
  const reachable = s === "healthy" || s === "online";
  const ms = row.extra?.response_time_ms;
  return {
    reachable,
    latency_ms: ms != null ? Math.round(ms) : null,
  };
}

function statusDot(ok: boolean) {
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: ok ? "#22c55e" : "#ef4444",
        marginRight: 6,
        flexShrink: 0,
      }}
    />
  );
}

function certColor(days: number | null): string {
  if (days === null) return "#6b7280";
  if (days > 60) return "#22c55e";
  if (days > 30) return "#f59e0b";
  return "#ef4444";
}

export default function Health({ theme, token }: { theme: "dark" | "light"; token: string }) {
  const isDark = theme === "dark";
  const bg = isDark ? "#0f1117" : "#f8fafc";
  const card = isDark ? "#1a1d27" : "#ffffff";
  const border = isDark ? "#2a2d3a" : "#e2e8f0";
  const text = isDark ? "#e2e8f0" : "#1e293b";
  const muted = isDark ? "#6b7280" : "#94a3b8";

  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [meshNodes, setMeshNodes] = useState<MeshStatusPayload["nodes"]>([]);
  const [error, setError] = useState<string | null>(null);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);

  const [agents, setAgents] = useState<LaunchAgentRow[] | null>(null);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [agentsErr, setAgentsErr] = useState(false);

  const fetchSummary = useCallback(async () => {
    try {
      const bundled = await Promise.all([
        apiJson<MeshStatusPayload>("/v1/mesh/status"),
        apiJson<HomeSummary>("/v1/home/summary"),
        apiJson<unknown>("/health"),
      ]);
      const mesh = bundled[0];
      const home = bundled[1];
      const byName = Object.fromEntries(
        mesh.nodes.map((n) => [n.name.toLowerCase(), n])
      );
      const data: HomeSummary = {
        nodes: {
          brain: meshRowToNodeSummary(byName["brain"]),
          gateway: meshRowToNodeSummary(byName["gateway"]),
          endpoint: meshRowToNodeSummary(byName["endpoint"]),
        },
        cert_days_remaining: home.cert_days_remaining ?? null,
        costs_today_usd: home.costs_today_usd ?? null,
        last_overnight_run: home.last_overnight_run ?? null,
        cached_at: home.cached_at ?? mesh.checked_at,
      };
      setSummary(data);
      setMeshNodes(mesh.nodes);
      setFetchedAt(new Date());
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [token]);

  const fetchAgents = useCallback(async () => {
    setAgentsLoading(true);
    setAgentsErr(false);
    try {
      const res = await apiFetch("/v1/health/agents");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { agents: LaunchAgentRow[] };
      setAgents(data.agents ?? []);
    } catch {
      setAgents(null);
      setAgentsErr(true);
    } finally {
      setAgentsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchSummary();
    fetchAgents();
    const t = setInterval(() => {
      fetchSummary();
      fetchAgents();
    }, REFRESH_MS);
    return () => clearInterval(t);
  }, [fetchSummary, fetchAgents]);

  const sectionStyle = {
    background: card,
    border: `1px solid ${border}`,
    borderRadius: 8,
    marginBottom: 16,
    overflow: "hidden" as const,
  };

  const sectionHeader = {
    padding: "12px 16px",
    borderBottom: `1px solid ${border}`,
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  };

  const labelStyle = {
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: "0.08em",
    textTransform: "uppercase" as const,
    color: muted,
  };

  const NODE_ICONS: Record<string, ReactNode> = {
    brain: <Cpu className="w-4 h-4 opacity-60" />,
    gateway: <Globe className="w-4 h-4 opacity-60" />,
    endpoint: <Monitor className="w-4 h-4 opacity-60" />,
    sandbox: <FlaskConical className="w-4 h-4 opacity-60" />,
  };

  return (
    <div style={{ background: bg, minHeight: "100vh", padding: "20px 24px", color: text, fontFamily: "system-ui, sans-serif" }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Health</h1>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          {fetchedAt && (
            <span style={{ fontSize: 11, color: muted }}>
              Updated {fetchedAt.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => {
              fetchSummary();
              fetchAgents();
            }}
            style={{ fontSize: 12, padding: "6px 12px", borderRadius: 6, border: `1px solid ${border}`, background: "transparent", color: text, cursor: "pointer" }}
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div style={{ background: "#1f1215", border: "1px solid #ef4444", borderRadius: 8, padding: "12px 16px", marginBottom: 16, color: "#ef4444", fontSize: 13 }}>
          Failed to load: {error}
        </div>
      )}

      {/* Node Reachability */}
      <div style={sectionStyle}>
        <div style={sectionHeader}>
          <span style={labelStyle}>Node Reachability</span>
          {summary && (
            <span style={{ fontSize: 11, color: muted }}>
              cached · refreshes every 60s
            </span>
          )}
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns:
              meshNodes.length > 0 ? `repeat(${meshNodes.length}, 1fr)` : "1fr",
            gap: 0,
          }}
        >
          {meshNodes.length === 0 ? (
            <div style={{ padding: "14px 16px" }}>
              <span style={{ fontSize: 12, color: muted }}>{!summary && !error ? "Loading…" : "—"}</span>
            </div>
          ) : (
            meshNodes.map((node, i) => {
              const nd = meshRowToNodeSummary(node);
              return (
                <div
                  key={node.name}
                  style={{
                    padding: "14px 16px",
                    borderRight: i < meshNodes.length - 1 ? `1px solid ${border}` : "none",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", marginBottom: 6, gap: 6 }}>
                    {statusDot(nd.reachable)}
                    {NODE_ICONS[node.name]}
                    <span style={{ fontWeight: 600, fontSize: 14 }}>{node.display_name}</span>
                  </div>
                  <div style={{ fontSize: 12, color: muted, marginBottom: 6 }}>
                    {node.tailscale_ip ?? "—"}
                  </div>
                  <div style={{ fontSize: 12 }}>
                    <span style={{ color: nd.reachable ? "#22c55e" : "#ef4444" }}>
                      {nd.reachable ? "Reachable" : "Unreachable"}
                    </span>
                    {nd.latency_ms != null && (
                      <span style={{ color: muted, marginLeft: 6 }}>{nd.latency_ms}ms</span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Brain Services */}
      <div style={sectionStyle}>
        <div style={sectionHeader}>
          <span style={labelStyle}>Brain Services</span>
        </div>
        <div style={{ padding: "14px 16px" }}>
          {agentsLoading && (
            <span style={{ fontSize: 12, color: muted }}>Loading…</span>
          )}
          {!agentsLoading && agentsErr && (
            <span style={{ fontSize: 12, color: "#f59e0b" }}>Agents unavailable</span>
          )}
          {!agentsLoading && !agentsErr && agents && agents.length === 0 && (
            <span style={{ fontSize: 12, color: muted }}>—</span>
          )}
          {!agentsLoading && !agentsErr && agents && agents.length > 0 && (() => {
            const alphaList = agents.filter((a) => a.label.includes("alpha"));
            const coreList = agents.filter((a) => !a.label.includes("alpha"));
            const renderCard = (a: LaunchAgentRow) => {
              const colors = agentBadgeColors(a.status, isDark);
              const showExit =
                a.exit_code != null && a.exit_code !== 0;
              return (
                <div
                  key={a.label}
                  style={{
                    padding: "12px 14px",
                    borderRadius: 8,
                    border: `1px solid ${border}`,
                    marginBottom: 10,
                    background: isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontWeight: 600, fontSize: 13, fontFamily: "ui-monospace, monospace" }}>
                      {agentShortLabel(a.label)}
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        textTransform: "uppercase",
                        letterSpacing: "0.06em",
                        padding: "3px 8px",
                        borderRadius: 4,
                        background: colors.bg,
                        color: colors.fg,
                      }}
                    >
                      {a.status.replace("_", " ")}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: muted, marginTop: 8, display: "flex", gap: 12, flexWrap: "wrap" }}>
                    <span>
                      PID:{" "}
                      <span style={{ color: text }}>{a.pid != null ? a.pid : "—"}</span>
                    </span>
                    {showExit && (
                      <span style={{ color: "#ef4444" }}>
                        Exit: {a.exit_code}
                      </span>
                    )}
                  </div>
                </div>
              );
            };
            return (
              <div>
                {alphaList.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ ...labelStyle, marginBottom: 10 }}>Alpha</div>
                    {alphaList.map(renderCard)}
                  </div>
                )}
                {coreList.length > 0 && (
                  <div>
                    <div style={{ ...labelStyle, marginBottom: 10 }}>Core</div>
                    {coreList.map(renderCard)}
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      </div>

      {/* LaunchAgents */}
      <div style={sectionStyle}>
        <div style={sectionHeader}>
          <span style={labelStyle}>LaunchAgents</span>
        </div>
        <div style={{ padding: "14px 16px" }}>
          {(() => {
            const known = ['brain', 'executor', 'watchdog', 'buddy', 'power_sampler'] as const;
            const agentMap = new Map((agents ?? []).map((a) => [agentShortLabel(a.label), a]));
            return (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>
                {known.map((name) => {
                  const match = agentMap.get(name) ?? agentMap.get(`alpha_${name}`);
                  const colors = match
                    ? agentBadgeColors(match.status, isDark)
                    : { bg: isDark ? 'rgba(107,114,128,0.25)' : 'rgba(148,163,184,0.35)', fg: isDark ? '#9ca3af' : '#64748b' };
                  const label = match ? match.status.replace('_', ' ') : 'status check pending';
                  const pid = match?.pid;
                  return (
                    <div
                      key={name}
                      style={{
                        padding: '10px 12px',
                        borderRadius: 8,
                        border: `1px solid ${border}`,
                        background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                        <span style={{ fontWeight: 600, fontSize: 12, fontFamily: 'ui-monospace, monospace' }}>{name}</span>
                        <span
                          style={{
                            fontSize: 9,
                            fontWeight: 700,
                            textTransform: 'uppercase',
                            letterSpacing: '0.06em',
                            padding: '2px 6px',
                            borderRadius: 4,
                            background: colors.bg,
                            color: colors.fg,
                          }}
                        >
                          {label}
                        </span>
                      </div>
                      {pid != null && (
                        <div style={{ fontSize: 10, color: muted, marginTop: 4 }}>
                          PID: <span style={{ color: text }}>{pid}</span>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })()}
        </div>
      </div>

      {/* System Stats */}
      <div style={sectionStyle}>
        <div style={sectionHeader}>
          <span style={labelStyle}>System</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 0 }}>

          {/* Cert */}
          <div style={{ padding: "14px 16px", borderRight: `1px solid ${border}` }}>
            <div style={{ fontSize: 11, color: muted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>TLS Cert</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: certColor(summary?.cert_days_remaining ?? null) }}>
              {summary?.cert_days_remaining != null ? `${summary.cert_days_remaining}d` : "—"}
            </div>
            <div style={{ fontSize: 11, color: muted, marginTop: 2 }}>days remaining</div>
          </div>

          {/* Costs */}
          <div style={{ padding: "14px 16px", borderRight: `1px solid ${border}` }}>
            <div style={{ fontSize: 11, color: muted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>Cloud Spend Today</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>
              {summary?.costs_today_usd != null ? `$${summary.costs_today_usd.toFixed(4)}` : "—"}
            </div>
            <div style={{ fontSize: 11, color: muted, marginTop: 2 }}>USD</div>
          </div>

          {/* Overnight */}
          <div style={{ padding: "14px 16px" }}>
            <div style={{ fontSize: 11, color: muted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>Last Overnight</div>
            {summary?.last_overnight_run ? (
              <>
                <div style={{ fontSize: 14, fontWeight: 600, color: summary.last_overnight_run.status === "pass" ? "#22c55e" : "#f59e0b" }}>
                  {summary.last_overnight_run.status}
                </div>
                <div style={{ fontSize: 11, color: muted, marginTop: 2 }}>
                  {new Date(summary.last_overnight_run.ran_at).toLocaleDateString()}
                </div>
              </>
            ) : (
              <div style={{ fontSize: 14, color: muted }}>No runs yet</div>
            )}
          </div>

        </div>
      </div>

      <div style={{ fontSize: 11, color: muted, textAlign: "right", marginTop: 8 }}>
        Auto-refreshes every 60s
      </div>
    </div>
  );
}
