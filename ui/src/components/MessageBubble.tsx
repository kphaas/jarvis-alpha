import { useState } from "react";
import { apiJson } from "../lib/apiFetch";

export interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
  model_used?: string | null;
  memory_injected?: boolean;
  latency_ms?: number | null;
  council_detail?: Record<string, string> | null;
  councilStreams?: Record<string, string>;
  streaming?: boolean;
  complexity?: number;
  thread_id?: string;
}

interface Props {
  msg: Message;
  showCouncilPanels?: boolean;
  onEscalated?: () => void;
}

const MODEL_COLOR: Record<string, { color: string; bg: string; border: string }> = {
  local:               { color: "#444441", bg: "#F1EFE8", border: "#D8D5CC" },
  claude:              { color: "#3C3489", bg: "#EEEDFE", border: "#C4C0F5" },
  perplexity:          { color: "#27500A", bg: "#EAF3DE", border: "#B8D99E" },
  gemini:              { color: "#633806", bg: "#FAEEDA", border: "#EFC898" },
  "council/synthesis": { color: "#3C3489", bg: "#EEEDFE", border: "#C4C0F5" },
};

const COUNCIL_TABS = ["claude", "perplexity", "gemini", "synthesis"] as const;
const TAB_LABEL: Record<string, string> = {
  claude: "Claude", perplexity: "Perplexity", gemini: "Gemini", synthesis: "Synthesis",
};

function modelColor(model: string | null | undefined) {
  if (!model) return MODEL_COLOR["local"];
  const key = Object.keys(MODEL_COLOR).find(k => model.toLowerCase().includes(k));
  return key ? MODEL_COLOR[key] : MODEL_COLOR["local"];
}

function modelLabel(model: string | null | undefined): string {
  if (!model) return "auto";
  if (model.includes("council")) return "Council";
  if (model.includes("claude")) return "Claude";
  if (model.includes("perplexity")) return "Perplexity";
  if (model.includes("gemini")) return "Gemini";
  return "Local";
}

export function MessageBubble({ msg, showCouncilPanels, onEscalated }: Props) {
  const [escalating, setEscalating] = useState(false);
  const [escalated, setEscalated]   = useState(false);
  const [hovered, setHovered]       = useState(false);
  const [activeTab, setActiveTab]   = useState<string>("claude");

  const isUser         = msg.role === "user";
  const isCouncil      = !!msg.council_detail && Object.keys(msg.council_detail).length > 0;
  const showPanels     = !!showCouncilPanels && isCouncil;
  const panelData      = msg.council_detail ?? {};
  const isHighComplexity = (msg.complexity ?? 0) >= 4;
  const mc             = modelColor(msg.model_used);

  // Determine synthesis text (the main assistant content when council)
  const synthesisText  = isCouncil ? msg.content : null;

  async function handleEscalate() {
    if (!msg.thread_id || escalated) return;
    setEscalating(true);
    try {
      await apiJson(`/v1/threads/${msg.thread_id}/escalate`, {
        method: "POST",
        body: JSON.stringify({ reason: "Manual escalation from chat" }),
      });
      setEscalated(true);
      onEscalated?.();
    } catch {}
    setEscalating(false);
  }

  // ── USER MESSAGE ──────────────────────────────────────────────────────────
  if (isUser) {
    return (
      <div style={{
        display: "flex", justifyContent: "flex-end",
        marginBottom: 20, animation: "msgFadeIn 0.15s ease",
      }}>
        <div style={{ maxWidth: 560 }}>
          <div style={{
            fontSize: 11, fontWeight: 500, color: "var(--color-text-tertiary)",
            textAlign: "right", marginBottom: 4, letterSpacing: "0.01em",
          }}>You</div>
          <div style={{
            fontSize: 13.5, lineHeight: 1.7,
            color: "var(--color-text-primary)",
            textAlign: "right",
          }}>
            {msg.content}
          </div>
        </div>
      </div>
    );
  }

  // ── JARVIS MESSAGE ────────────────────────────────────────────────────────
  return (
    <div
      style={{ marginBottom: 24, animation: "msgFadeIn 0.15s ease" }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Header row: JARVIS label + model tag + latency */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6, marginBottom: 6,
      }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)",
          letterSpacing: "0.02em",
        }}>JARVIS</span>
        {msg.model_used && (
          <span style={{
            fontSize: 10, padding: "1px 6px", borderRadius: 4,
            background: mc.bg, color: mc.color,
            border: `0.5px solid ${mc.border}`,
            fontWeight: 500,
          }}>{modelLabel(msg.model_used)}</span>
        )}
        {msg.memory_injected && (
          <span style={{
            fontSize: 10, padding: "1px 6px", borderRadius: 4,
            background: "#E1F5EE", color: "#085041",
            border: "0.5px solid #A8D9C8", fontWeight: 500,
          }}>from memory</span>
        )}
        {msg.latency_ms && (
          <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>{msg.latency_ms}ms</span>
        )}
        {isCouncil && (
          <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>
            {showPanels ? "· Showing Council" : "· Council"}
          </span>
        )}
        {hovered && !escalated && msg.thread_id && (
          <button onClick={handleEscalate} disabled={escalating} style={{
            marginLeft: "auto",
            fontSize: 10, padding: "1px 6px", borderRadius: 4, cursor: "pointer",
            background: "transparent", border: "0.5px solid #BA7517",
            color: "#BA7517", fontFamily: "var(--font-sans)",
            opacity: escalating ? 0.5 : 1,
          }}>
            {escalating ? "Queuing…" : "Send to overnight"}
          </button>
        )}
        {escalated && (
          <span style={{ fontSize: 10, color: "#BA7517", marginLeft: "auto" }}>◑ Queued for tonight</span>
        )}
      </div>

      {/* Message body */}
      <div style={{
        fontSize: 13.5, lineHeight: 1.7, color: "var(--color-text-primary)",
        whiteSpace: "pre-wrap", wordBreak: "break-word",
      }}>
        {msg.content}
        {msg.streaming && (
          <span style={{
            display: "inline-block", width: 2, height: 14,
            background: "var(--color-text-primary)",
            marginLeft: 2, verticalAlign: "text-bottom",
            animation: "blink 1s step-end infinite",
          }} />
        )}
      </div>

      {/* High complexity prompt */}
      {isHighComplexity && !escalated && msg.thread_id && (
        <div style={{
          marginTop: 10, padding: "8px 12px", borderRadius: 8,
          background: "#FAEEDA", border: "0.5px solid #EFC898",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <span style={{ fontSize: 11, color: "#633806" }}>Complex question — run overnight for deeper results?</span>
          <button onClick={handleEscalate} style={{
            fontSize: 11, padding: "3px 10px", borderRadius: 5, cursor: "pointer",
            background: "#BA7517", border: "none", color: "#fff",
            fontFamily: "var(--font-sans)", fontWeight: 500,
          }}>Queue</button>
        </div>
      )}

      {/* Council tabs */}
      {showPanels && Object.keys(panelData).length > 0 && (
        <div style={{ marginTop: 12 }}>
          {/* Tab bar */}
          <div style={{
            display: "flex", gap: 0,
            borderBottom: "1px solid var(--color-border-tertiary)",
            marginBottom: 0,
          }}>
            {COUNCIL_TABS.map(tab => {
              const isActive = activeTab === tab;
              const tabData  = tab === "synthesis" ? synthesisText : panelData[tab];
              const hasData  = !!tabData;
              const tc       = tab === "synthesis" ? MODEL_COLOR["claude"] : modelColor(tab);
              return (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  style={{
                    padding: "7px 14px", fontSize: 11, fontWeight: isActive ? 600 : 400,
                    background: "transparent", border: "none", cursor: "pointer",
                    color: isActive ? tc.color : "var(--color-text-tertiary)",
                    borderBottom: isActive ? `2px solid ${tc.color}` : "2px solid transparent",
                    marginBottom: -1, fontFamily: "var(--font-sans)",
                    transition: "color 0.15s",
                    opacity: hasData ? 1 : 0.4,
                  }}
                >
                  {TAB_LABEL[tab]}
                  {tab === "synthesis" && (
                    <span style={{ marginLeft: 4, fontSize: 9 }}>⚡</span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Tab content */}
          <div style={{
            padding: "12px 0",
            fontSize: 12.5, lineHeight: 1.65,
            color: "var(--color-text-primary)",
            whiteSpace: "pre-wrap", wordBreak: "break-word",
            minHeight: 40,
          }}>
            {activeTab === "synthesis"
              ? (synthesisText || <span style={{ opacity: 0.4 }}>waiting…</span>)
              : (panelData[activeTab] || <span style={{ opacity: 0.4, fontStyle: "italic" }}>waiting…</span>)
            }
          </div>
        </div>
      )}
    </div>
  );
}
