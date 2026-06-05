import { useState, useEffect, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import { Loader2, Cpu, Globe, Monitor, FlaskConical, Server, Router } from "lucide-react";
import { apiFetch, apiJson } from "../lib/apiFetch";
import { WatchdogPanel } from "../components/mesh/WatchdogPanel";

const REFRESH_MS = 30_000;

interface MeshNodeExtra {
  response_time_ms?: number;
  wan_up_mbps?: number;
  wan_down_mbps?: number;
  client_count?: number;
  wan_status?: string;
  last_commit?: string;
  last_commit_at?: string;
}

interface MeshNode {
  name: string;
  display_name: string;
  role: string;
  node_type: string;
  tailscale_ip: string | null;
  status: string;
  cert_status: "green" | "amber" | "red" | null;
  cert_pct_remaining: number | null;
  cert_days_remaining: number | null;
  extra: MeshNodeExtra;
}

interface MeshStatus {
  mesh_status: "nominal" | "degraded" | "critical";
  checked_at: string;
  nodes: MeshNode[];
}

interface UdmSummary {
  reachable: boolean;
  wan_up_mbps: number | null;
  wan_down_mbps: number | null;
  client_count: number | null;
  wan_status: string;
}

interface MeshCertApiRow {
  node: string;
  domain: string;
  expires: string;
  days_remaining: number;
  status: string;
  source: string;
}

function certStatusFromApi(status: string): "green" | "amber" | "red" {
  const s = status.toLowerCase();
  if (s === "ok") return "green";
  if (s === "warning") return "amber";
  return "red";
}

function mergeMeshCerts(nodes: MeshNode[], certs: MeshCertApiRow[]): MeshNode[] {
  const by = Object.fromEntries(certs.map((c) => [c.node.toLowerCase(), c]));
  return nodes.map((n) => {
    const c = by[n.name] as MeshCertApiRow | undefined;
    if (!c) return n;
    return {
      ...n,
      cert_days_remaining: n.cert_days_remaining ?? c.days_remaining,
      cert_status: n.cert_status ?? certStatusFromApi(c.status),
    };
  });
}

const STATUS_GREEN = "#00ff88";
const STATUS_AMBER = "#f59e0b";
const STATUS_RED = "#ef4444";

function statusColor(status: string | null | undefined): string {
  const s = status?.toLowerCase() ?? "";
  if (s === "healthy" || s === "online") return STATUS_GREEN;
  if (s === "degraded") return STATUS_AMBER;
  return STATUS_RED;
}

function certBarColor(cert: string | null): string {
  if (cert === "green") return STATUS_GREEN;
  if (cert === "amber") return STATUS_AMBER;
  if (cert === "red") return STATUS_RED;
  return "rgba(255,255,255,0.2)";
}

function minsAgoLabel(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const mins = Math.floor((Date.now() - t) / 60_000);
  if (mins < 1) return "just now";
  if (mins === 1) return "1 min ago";
  return `${mins} mins ago`;
}

function NodeHealthStrip({ nodes, theme }: { nodes: MeshNode[]; theme: "dark" | "light" }) {
  const isDark = theme === "dark";
  const border = isDark ? "border-white/10" : "border-[#141414]/10";
  const subtle = isDark ? "bg-white/5" : "bg-[#141414]/5";
  return (
    <div className={`rounded-xl border ${border} ${subtle} px-3 py-2 overflow-x-auto`}>
      <div className="flex items-stretch gap-3 min-w-min">
        {nodes.map((node) => (
          <motion.div
            key={node.name}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 shrink-0 pr-3 border-r border-white/10 last:border-0 last:pr-0"
          >
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: statusColor(node.status) }} />
            <div className="flex flex-col min-w-0">
              <span className={`text-[10px] font-bold truncate ${isDark ? "text-white/90" : "text-[#141414]/90"}`}>
                {node.display_name}
              </span>
              <span className="text-[9px] font-mono uppercase opacity-50 truncate">
                {(node.status ?? "").replace(/_/g, " ")}
                {node.extra?.response_time_ms != null ? ` · ${node.extra.response_time_ms}ms` : ""}
              </span>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

interface LogEntry {
  ts: string;
  level: string;
  service: string;
  node: string;
  message: string;
}

function parseStatusCodeFromMessage(message: string): number {
  const afterHttp = message.match(/HTTP\/1\.1\s+(\d{3})\b/);
  if (afterHttp) return parseInt(afterHttp[1], 10);
  const triples = message.match(/\d{3}/g);
  if (triples?.length) return parseInt(triples[triples.length - 1], 10);
  return 200;
}

function parseMethodPath(message: string): string {
  const quoted = message.match(
    /"(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+([^"\s]+)/i
  );
  if (quoted) return `${quoted[1]} ${quoted[2]}`;
  const loose = message.match(/\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(\S+)/i);
  if (loose) return `${loose[1]} ${loose[2]}`;
  return message.trim() || "—";
}

function relativeSecsAgo(iso: string): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const secs = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  return `${h}h ago`;
}

function statusDotColor(code: number): string {
  if (code >= 500) return STATUS_RED;
  if (code >= 400) return STATUS_AMBER;
  return STATUS_GREEN;
}

function RequestTicker({ theme }: { theme: "dark" | "light" }) {
  const isDark = theme === "dark";
  const border = isDark ? "border-white/10" : "border-[#141414]/10";
  const subtle = isDark ? "bg-white/5" : "bg-[#141414]/5";
  const fg = isDark ? "text-white/85" : "text-[#141414]/85";
  const muted = isDark ? "text-white/40" : "text-[#141414]/45";
  const [entries, setEntries] = useState<LogEntry[]>([]);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(
        "/v1/logs/query?limit=10&level=INFO&service=alpha_brain_access"
      );
      const data = (await res.json()) as {
        status: string;
        entries?: LogEntry[];
      };
      if (!res.ok || data.status === "error" || !data.entries?.length) {
        setEntries([]);
        return;
      }
      setEntries(data.entries);
    } catch {
      setEntries([]);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15_000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className={`rounded-xl border ${border} ${subtle} px-3 py-2 overflow-x-auto`}>
      <div className="flex items-center gap-2 mb-2">
        <span className="w-1.5 h-1.5 rounded-full shrink-0 bg-emerald-400 animate-pulse" />
        <p className="text-[9px] font-mono uppercase opacity-40">LIVE ACTIVITY</p>
      </div>
      {entries.length === 0 ? (
        <p className={`text-[9px] font-mono ${muted}`}>No recent activity</p>
      ) : (
        <div className="flex items-stretch gap-2 min-w-min">
          {entries.map((e, i) => {
            const code = parseStatusCodeFromMessage(e.message);
            const label = parseMethodPath(e.message);
            const short =
              label.length > 30 ? `${label.slice(0, 27)}…` : label;
            return (
              <div
                key={`${e.ts}-${i}`}
                className={`flex items-center gap-1.5 shrink-0 rounded-lg border px-2 py-1 ${
                  isDark ? "border-white/10 bg-white/[0.03]" : "border-[#141414]/10 bg-[#141414]/[0.03]"
                }`}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ backgroundColor: statusDotColor(code) }}
                />
                <span className={`text-[9px] font-mono truncate max-w-[11rem] ${fg}`}>
                  {short}
                </span>
                <span className={`text-[9px] font-mono shrink-0 opacity-50 ${fg}`}>
                  {relativeSecsAgo(e.ts)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CertBadgeRow({ nodes, theme }: { nodes: MeshNode[]; theme: "dark" | "light" }) {
  const isDark = theme === "dark";
  const border = isDark ? "border-white/10" : "border-[#141414]/10";
  const withCert = nodes.filter(
    (n) => n.cert_status != null && n.cert_days_remaining != null && n.cert_pct_remaining != null
  );
  if (withCert.length === 0) return null;
  return (
    <div className={`rounded-xl border ${border} px-3 py-2`}>
      <p className="text-[9px] font-mono uppercase opacity-40 mb-2">TLS Certificates</p>
      <div className="flex flex-wrap gap-2 items-center">
        {withCert.map((n) => (
          <div
            key={n.name}
            className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 min-w-[120px]"
          >
            <span className="text-[9px] font-bold uppercase shrink-0">{n.name.toUpperCase()}</span>
            <span className="text-[9px] font-mono opacity-50 shrink-0">{n.cert_days_remaining}d</span>
            <div className="flex-1 h-1.5 rounded-full bg-white/10 overflow-hidden min-w-[40px]">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.min(100, Math.max(0, n.cert_pct_remaining ?? 0))}%`,
                  backgroundColor: certBarColor(n.cert_status),
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const TOPO_POSITIONS: Record<string, { x: number; y: number }> = {
  brain:    { x: 380, y: 220 },
  gateway:  { x: 200, y: 95 },
  endpoint: { x: 560, y: 95 },
  iphone:   { x: 100, y: 380 },
  unraid:   { x: 280, y: 380 },
  sandbox:  { x: 640, y: 380 },
};

const BRAIN_LINKS = ["gateway", "endpoint", "unraid", "sandbox"] as const;

function TopologyDiagram({
  nodes,
  theme,
  udm,
}: {
  nodes: MeshNode[];
  theme: "dark" | "light";
  udm?: UdmSummary | null;
}) {
  const isDark = theme === "dark";
  const W = 760;
  const H = 500;
  const barFill = isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)";
  const barStroke = isDark ? "rgba(255,255,255,0.14)" : "rgba(0,0,0,0.12)";
  const barText = isDark ? "rgba(255,255,255,0.75)" : "rgba(0,0,0,0.75)";
  const barMuted = isDark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.45)";
  const reachable = udm?.reachable === true;
  const dotFill = reachable ? STATUS_GREEN : STATUS_RED;
  const wanUpStr = udm?.wan_up_mbps != null ? String(udm.wan_up_mbps) : "—";
  const wanDownStr = udm?.wan_down_mbps != null ? String(udm.wan_down_mbps) : "—";
  const clientsStr = udm?.client_count != null ? String(udm.client_count) : "—";
  const barY = H - 40;
  const barH = 32;
  const barMidY = barY + barH / 2;
  const barPad = 20;
  const innerW = W - 2 * barPad;
  const colW = innerW / 5;
  const byName = Object.fromEntries(nodes.map((n) => [n.name, n]));
  const topoNodes = nodes.filter((n) => TOPO_POSITIONS[n.name]);
  const center = TOPO_POSITIONS.brain;

  const glyphs: Record<string, string> = {
    brain: "⬡", gateway: "⬢", endpoint: "▣", unraid: "◉", iphone: "◎", sandbox: "⬡",
  };

  function iconForTopoNode(name: string) {
    switch (name) {
      case "brain":
        return Cpu;
      case "gateway":
        return Globe;
      case "endpoint":
        return Monitor;
      case "sandbox":
        return FlaskConical;
      default:
        return Server;
    }
  }

  const internetStroke = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.08)";
  const internetDotFill = isDark ? "rgba(255,255,255,0.45)" : "rgba(0,0,0,0.35)";

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: H }}>
      {BRAIN_LINKS.map((id, idx) => {
        const node = byName[id];
        const pos = TOPO_POSITIONS[id];
        if (!node || !pos) return null;
        const strokeCol = statusColor(node.status);
        const d = `M ${center.x},${center.y} L ${pos.x},${pos.y}`;
        const pathId = `path-brain-${id}`;
        const durSec = [3, 3.5, 4, 4.5][idx] ?? 3;
        return (
          <g key={`link-${id}`}>
            <path
              id={pathId}
              d={d}
              stroke={strokeCol}
              strokeWidth={1.2}
              opacity={0.45}
              fill="none"
            />
            <circle r="2.5" fill={strokeCol} opacity={0.7}>
              <animateMotion dur={`${durSec}s`} repeatCount="indefinite">
                <mpath xlinkHref={`#${pathId}`} />
              </animateMotion>
            </circle>
            <circle r="2" fill={strokeCol} opacity={0.4}>
              <animateMotion
                dur={`${durSec}s`}
                repeatCount="indefinite"
                keyPoints="1;0"
                keyTimes="0;1"
                calcMode="linear"
              >
                <mpath xlinkHref={`#${pathId}`} />
              </animateMotion>
            </circle>
          </g>
        );
      })}
      {(() => {
        const iphoneNode = byName["iphone"];
        const iphonePos = TOPO_POSITIONS["iphone"];
        const gatewayPos = TOPO_POSITIONS["gateway"];
        if (!iphoneNode || !iphonePos || !gatewayPos) return null;
        const strokeCol = statusColor(iphoneNode.status);
        const d = `M ${gatewayPos.x},${gatewayPos.y} L ${iphonePos.x},${iphonePos.y}`;
        const pathId = "path-iphone-gateway";
        return (
          <g key="link-iphone-gateway">
            <path
              id={pathId}
              d={d}
              stroke={strokeCol}
              strokeWidth={1.2}
              opacity={0.45}
              fill="none"
            />
            <circle r="2.5" fill={strokeCol} opacity={0.7}>
              <animateMotion dur="3.2s" repeatCount="indefinite">
                <mpath xlinkHref={`#${pathId}`} />
              </animateMotion>
            </circle>
            <circle r="2" fill={strokeCol} opacity={0.4}>
              <animateMotion
                dur="3.65s"
                repeatCount="indefinite"
                keyPoints="1;0"
                keyTimes="0;1"
                calcMode="linear"
              >
                <mpath xlinkHref={`#${pathId}`} />
              </animateMotion>
            </circle>
          </g>
        );
      })()}

      <ellipse cx="310" cy="30" rx="48" ry="12"
        fill="none"
        stroke={isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.1)"}
        strokeWidth="1" strokeDasharray="3 2"
      />
      <text x="310" y="34" textAnchor="middle" fontSize="8"
        fill={isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.25)"}
      >INTERNET</text>
      <path
        id="path-gateway-internet"
        d={`M ${TOPO_POSITIONS.gateway.x},${TOPO_POSITIONS.gateway.y} L 310,42`}
        stroke={internetStroke}
        strokeWidth={1}
        strokeDasharray="3 2"
        fill="none"
      />
      <circle r="2.5" fill={internetDotFill} opacity={0.3}>
        <animateMotion dur="5s" repeatCount="indefinite">
          <mpath xlinkHref="#path-gateway-internet" />
        </animateMotion>
      </circle>

      {topoNodes.map((node) => {
        const pos = TOPO_POSITIONS[node.name];
        if (!pos) return null;
        const col = statusColor(node.status);
        const isBrain = node.name === "brain";
        const rOuter = isBrain ? 38 : 28;
        const rInner = isBrain ? 32 : 22;
        return (
          <g key={`node-${node.name}`}>
            <circle cx={pos.x} cy={pos.y} r={rOuter}
              fill="none" stroke={col}
              strokeWidth={isBrain ? 2 : 1.5} opacity={0.55}
            />
            {isBrain && (
              <circle cx={pos.x} cy={pos.y} r="38"
                fill="none" stroke={col} strokeWidth="1" opacity="0.25"
              >
                <animate attributeName="r" values="38;52;38" dur="3s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.25;0;0.25" dur="3s" repeatCount="indefinite" />
              </circle>
            )}
            <circle cx={pos.x} cy={pos.y} r={rInner} fill={col} opacity={0.12} />
            <circle cx={pos.x + (isBrain ? 22 : 15)} cy={pos.y - (isBrain ? 22 : 15)} r="5" fill={col} />
            <text x={pos.x} y={pos.y + (isBrain ? 52 : 44)}
              textAnchor="middle" fontSize={isBrain ? "11" : "10"} fontWeight="bold"
              fill={isDark ? "rgba(255,255,255,0.85)" : "rgba(0,0,0,0.85)"}
            >{node.display_name}</text>
            <text x={pos.x} y={pos.y + (isBrain ? 64 : 55)}
              textAnchor="middle" fontSize="8"
              fill={isDark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.35)"}
            >{node.tailscale_ip ?? "—"}</text>
            <text x={pos.x} y={pos.y + 4}
              textAnchor="middle" fontSize={isBrain ? "16" : "13"}
              fill={col} opacity={0.95}
            >{glyphs[node.name] ?? "◎"}</text>
            {(() => {
              const Icon = iconForTopoNode(node.name);
              return (
                <foreignObject
                  x={pos.x - 8}
                  y={pos.y - 8}
                  width={16}
                  height={16}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      width: 16,
                      height: 16,
                      color: col,
                    }}
                  >
                    <Icon width={12} height={12} stroke="currentColor" fill="none" />
                  </div>
                </foreignObject>
              );
            })()}
          </g>
        );
      })}

      <rect
        x={barPad}
        y={barY}
        width={W - 2 * barPad}
        height={barH}
        rx={6}
        ry={6}
        fill={barFill}
        stroke={barStroke}
        strokeWidth={1}
      />
      <foreignObject x={barPad + 8} y={barMidY - 7} width={14} height={14}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: 14,
            height: 14,
            color: barText,
          }}
        >
          <Router width={14} height={14} stroke="currentColor" fill="none" />
        </div>
      </foreignObject>
      <circle cx={barPad + 28} cy={barMidY} r={3} fill={dotFill} />
      <text
        x={barPad + 42}
        y={barMidY}
        dominantBaseline="middle"
        textAnchor="start"
        fontSize="9"
        fontWeight={600}
        fill={barText}
        style={{ fontFamily: "ui-monospace, monospace" }}
      >
        NETWORK LAYER · UDM-PRO
      </text>
      <text
        x={barPad + colW * 2.5}
        y={barMidY}
        dominantBaseline="middle"
        textAnchor="middle"
        fontSize="9"
        fill={barText}
        style={{ fontFamily: "ui-monospace, monospace" }}
      >
        <tspan fill={barMuted}>WAN ↑ </tspan>
        <tspan fill={barText}>{wanUpStr}</tspan>
        <tspan fill={barMuted}> Mbps</tspan>
      </text>
      <text
        x={barPad + colW * 3.5}
        y={barMidY}
        dominantBaseline="middle"
        textAnchor="middle"
        fontSize="9"
        fill={barText}
        style={{ fontFamily: "ui-monospace, monospace" }}
      >
        <tspan fill={barMuted}>WAN ↓ </tspan>
        <tspan fill={barText}>{wanDownStr}</tspan>
        <tspan fill={barMuted}> Mbps</tspan>
      </text>
      <text
        x={barPad + colW * 4.5}
        y={barMidY}
        dominantBaseline="middle"
        textAnchor="middle"
        fontSize="9"
        fill={barText}
        style={{ fontFamily: "ui-monospace, monospace" }}
      >
        <tspan fill={barMuted}>Clients: </tspan>
        <tspan fill={barText}>{clientsStr}</tspan>
      </text>
    </svg>
  );
}

export default function Mesh({ theme }: { theme: "dark" | "light" }) {
  const [mesh, setMesh] = useState<MeshStatus | null>(null);
  const [udm, setUdm] = useState<UdmSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initialLoad = useRef(true);

  const isDark = theme === "dark";
  const border = isDark ? "border-white/10" : "border-[#141414]/10";
  const subtle = isDark ? "bg-white/5" : "bg-[#141414]/5";

  const load = useCallback(async () => {
    if (!initialLoad.current) setRefreshing(true);
    try {
      const [statusData, certsData, udmSummary] = await Promise.all([
        apiJson<MeshStatus>("/v1/mesh/status"),
        apiJson<MeshCertApiRow[]>("/v1/mesh/certs"),
        apiJson<UdmSummary>("/v1/unifi/summary").catch(() => null),
      ]);
      setMesh({
        ...statusData,
        nodes: mergeMeshCerts(statusData.nodes, certsData),
      });
      setUdm(udmSummary);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load mesh");
    } finally {
      setLoading(false);
      setRefreshing(false);
      initialLoad.current = false;
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 opacity-30">
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-sm">
        {error}
      </div>
    );
  }

  if (!mesh) return null;

  const headerPill =
    mesh.mesh_status === "nominal"
      ? { label: "SYSTEM NOMINAL", bg: "bg-emerald-500/15", fg: "text-emerald-400", border: "border-emerald-500/30", dot: "bg-emerald-400" }
      : mesh.mesh_status === "degraded"
      ? { label: "SYSTEM DEGRADED", bg: "bg-amber-500/15", fg: "text-amber-400", border: "border-amber-500/30", dot: "bg-amber-400" }
      : { label: "SYSTEM CRITICAL", bg: "bg-rose-500/15", fg: "text-rose-400", border: "border-rose-500/30", dot: "bg-rose-400" };

  return (
    <div className="space-y-5 max-w-5xl">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-serif italic text-3xl">Mesh</h1>
          <p className="text-xs font-mono uppercase mt-1 opacity-50">
            Live topology · TLS · 30s refresh
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex items-center gap-2">
            {refreshing && <Loader2 className="w-3.5 h-3.5 animate-spin opacity-40" />}
            <div className={`flex items-center gap-2 px-4 py-2 rounded-xl border text-xs font-mono font-bold ${headerPill.bg} ${headerPill.fg} ${headerPill.border}`}>
              <span className={`w-2 h-2 rounded-full ${headerPill.dot}`} />
              {headerPill.label}
            </div>
          </div>
          <span className="text-[9px] font-mono opacity-35">
            Last checked: {minsAgoLabel(mesh.checked_at)}
          </span>
        </div>
      </div>

      <NodeHealthStrip nodes={mesh.nodes} theme={theme} />

      <div className={`p-6 rounded-2xl border ${border} ${subtle}`}>
        <p className="text-[10px] font-mono uppercase opacity-40 mb-3">Network Topology</p>
        <TopologyDiagram nodes={mesh.nodes} theme={theme} udm={udm} />
      </div>

      <RequestTicker theme={theme} />

      <WatchdogPanel theme={theme} />

      <CertBadgeRow nodes={mesh.nodes} theme={theme} />
    </div>
  );
}
