import { useEffect, useState, useCallback } from "react";
import { apiJson } from "../lib/apiFetch";

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
    status: string;
    extra?: { response_time_ms?: number };
  }>;
}

interface HealthV1Payload {
  cert_days_remaining?: number | null;
  costs_today_usd?: number | null;
  last_overnight_run?: { status: string; ran_at: string } | null;
  cached_at?: string;
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
  const [error, setError] = useState<string | null>(null);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);

  const fetchSummary = useCallback(async () => {
    try {
      const [mesh, health] = await Promise.all([
        apiJson<MeshStatusPayload>("/v1/mesh/status"),
        apiJson<HealthV1Payload>("/v1/health"),
      ]);
      const byName = Object.fromEntries(
        mesh.nodes.map((n) => [n.name.toLowerCase(), n])
      );
      const data: HomeSummary = {
        nodes: {
          brain: meshRowToNodeSummary(byName["brain"]),
          gateway: meshRowToNodeSummary(byName["gateway"]),
          endpoint: meshRowToNodeSummary(byName["endpoint"]),
        },
        cert_days_remaining: health.cert_days_remaining ?? null,
        costs_today_usd: health.costs_today_usd ?? null,
        last_overnight_run: health.last_overnight_run ?? null,
        cached_at: health.cached_at ?? mesh.checked_at,
      };
      setSummary(data);
      setFetchedAt(new Date());
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [token]);

  useEffect(() => {
    fetchSummary();
    const t = setInterval(fetchSummary, REFRESH_MS);
    return () => clearInterval(t);
  }, [fetchSummary]);

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

  const nodes: { key: "brain" | "gateway" | "endpoint"; label: string; ip: string }[] = [
    { key: "brain", label: "Brain", ip: "100.64.166.22" },
    { key: "gateway", label: "Gateway", ip: "100.112.63.25" },
    { key: "endpoint", label: "Endpoint", ip: "100.87.223.31" },
  ];

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
            onClick={fetchSummary}
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
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 0 }}>
          {nodes.map((node, i) => {
            const nd = summary?.nodes[node.key];
            return (
              <div
                key={node.key}
                style={{ padding: "14px 16px", borderRight: i < 2 ? `1px solid ${border}` : "none" }}
              >
                <div style={{ display: "flex", alignItems: "center", marginBottom: 6 }}>
                  {statusDot(nd?.reachable ?? false)}
                  <span style={{ fontWeight: 600, fontSize: 14 }}>{node.label}</span>
                </div>
                <div style={{ fontSize: 12, color: muted, marginBottom: 6 }}>{node.ip}</div>
                <div style={{ fontSize: 12 }}>
                  <span style={{ color: nd?.reachable ? "#22c55e" : "#ef4444" }}>
                    {!summary ? "Loading…" : nd?.reachable ? "Reachable" : "Unreachable"}
                  </span>
                  {nd?.latency_ms != null && (
                    <span style={{ color: muted, marginLeft: 6 }}>{nd.latency_ms}ms</span>
                  )}
                </div>
              </div>
            );
          })}
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
