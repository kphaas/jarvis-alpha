import { useState, useRef, useEffect } from "react";

export interface ModelOption {
  id: string;
  label: string;
  provider: "local" | "claude" | "perplexity" | "gemini";
  costTier: "free" | "low" | "medium" | "high";
  speed: "fast" | "medium" | "slow";
  bestFor: string;
}

export const MODELS: ModelOption[] = [
  { id: "local",      label: "Local",          provider: "local",      costTier: "free",   speed: "fast",   bestFor: "Quick answers, code, private" },
  { id: "claude",     label: "Claude Sonnet",  provider: "claude",     costTier: "medium", speed: "medium", bestFor: "Reasoning, architecture, planning" },
  { id: "perplexity", label: "Perplexity",     provider: "perplexity", costTier: "low",    speed: "fast",   bestFor: "Web search, current events" },
  { id: "gemini",     label: "Gemini Flash",   provider: "gemini",     costTier: "low",    speed: "fast",   bestFor: "Structured output, long context" },
];

const PILL: Record<string, { bg: string; border: string; color: string; dot: string; send: string }> = {
  auto:       { bg: "rgba(55,138,221,0.12)",  border: "rgba(55,138,221,0.28)",  color: "#0C447C", dot: "#378ADD", send: "#378ADD" },
  local:      { bg: "rgba(95,94,90,0.1)",     border: "rgba(95,94,90,0.25)",    color: "#444441", dot: "#5F5E5A", send: "#5F5E5A" },
  claude:     { bg: "rgba(83,74,183,0.12)",   border: "rgba(83,74,183,0.28)",   color: "#3C3489", dot: "#534AB7", send: "#534AB7" },
  perplexity: { bg: "rgba(59,109,17,0.1)",    border: "rgba(59,109,17,0.25)",   color: "#27500A", dot: "#3B6D11", send: "#3B6D11" },
  gemini:     { bg: "rgba(186,117,23,0.1)",   border: "rgba(186,117,23,0.25)",  color: "#633806", dot: "#BA7517", send: "#BA7517" },
  council:    { bg: "rgba(83,74,183,0.1)",    border: "rgba(83,74,183,0.22)",   color: "#3C3489", dot: "#534AB7", send: "#534AB7" },
};

const COST: Record<string, string> = { free: "$0", low: "$", medium: "$$", high: "$$$" };
const SPEED: Record<string, string> = { fast: "Fast", medium: "Moderate", slow: "Slow" };

export interface ModelSelectorProps {
  selected: string[];
  onChange: (ids: string[]) => void;
}

export function ModelSelector({ selected, onChange }: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  function toggle(id: string) {
    if (id === "auto") { onChange([]); setOpen(false); return; }
    if (selected.includes(id)) {
      onChange(selected.filter(s => s !== id));
    } else if (selected.length < 3) {
      onChange([...selected, id]);
    }
  }

  const isAuto    = selected.length === 0;
  const isCouncil = selected.length >= 2;
  const activeKey = isAuto ? "auto" : isCouncil ? "council" : selected[0];
  const style     = PILL[activeKey] ?? PILL["auto"];

  const pillLabel = isAuto
    ? "Auto"
    : isCouncil
    ? `Council (${selected.length})`
    : MODELS.find(m => m.id === selected[0])?.label ?? selected[0];

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 5,
          padding: "5px 10px 5px 8px", borderRadius: 20,
          background: style.bg,
          border: `0.5px solid ${style.border}`,
          cursor: "pointer", fontSize: 11, fontWeight: 500,
          color: style.color, fontFamily: "var(--font-sans)",
          transition: "background 0.2s, color 0.2s, border-color 0.2s",
        }}
      >
        {isCouncil ? (
          <div style={{ display: "flex", gap: 2, alignItems: "center" }}>
            {selected.slice(0, 3).map(id => (
              <div key={id} style={{
                width: 5, height: 5, borderRadius: "50%",
                background: PILL[id]?.dot ?? "#888",
              }} />
            ))}
          </div>
        ) : (
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: style.dot }} />
        )}
        {pillLabel}
        <span style={{ fontSize: 8, opacity: 0.5, marginLeft: 1 }}>▾</span>
      </button>

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 200,
          width: 292, background: "var(--color-background-primary)",
          border: "0.5px solid var(--color-border-secondary)",
          borderRadius: "var(--border-radius-lg)", overflow: "hidden",
        }}>
          <div style={{
            padding: "8px 13px", borderBottom: "0.5px solid var(--color-border-tertiary)",
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}>
            <span style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)" }}>Choose model</span>
            <span style={{ fontSize: 9, color: "var(--color-text-tertiary)" }}>Tap 2+ for council</span>
          </div>

          <div
            onClick={() => toggle("auto")}
            style={{
              padding: "8px 13px", display: "flex", alignItems: "center", gap: 9,
              cursor: "pointer", borderBottom: "0.5px solid var(--color-border-tertiary)",
              background: isAuto ? "rgba(55,138,221,0.06)" : "transparent",
            }}
          >
            <div style={{
              width: 26, height: 26, borderRadius: 7, background: "#378ADD",
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}>
              <svg width="12" height="12" viewBox="0 0 16 16" fill="white">
                <path d="M8 1l1.5 4.5H14l-3.7 2.7 1.4 4.3L8 10l-3.7 2.5 1.4-4.3L2 5.5h4.5z"/>
              </svg>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-primary)" }}>Auto</div>
              <div style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>JARVIS picks based on complexity</div>
              <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
                <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: "#E6F1FB", color: "#0C447C", fontWeight: 500 }}>Smart routing</span>
                <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: "#EAF3DE", color: "#27500A", fontWeight: 500 }}>$0</span>
              </div>
            </div>
            {isAuto && <span style={{ color: "#378ADD", fontSize: 13 }}>✓</span>}
          </div>

          {MODELS.map(m => {
            const ps = PILL[m.provider];
            const isSel = selected.includes(m.id);
            return (
              <div
                key={m.id}
                onClick={() => toggle(m.id)}
                style={{
                  padding: "8px 13px", display: "flex", alignItems: "center", gap: 9,
                  cursor: "pointer", borderBottom: "0.5px solid var(--color-border-tertiary)",
                  background: isSel ? ps.bg : "transparent",
                  transition: "background 0.15s",
                }}
              >
                <div style={{
                  width: 26, height: 26, borderRadius: 7, background: ps.send,
                  display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                }}>
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="white">
                    <circle cx="5" cy="5" r="4" stroke="white" strokeWidth="1" fill="none"/>
                    <circle cx="5" cy="5" r="1.5"/>
                  </svg>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-primary)" }}>{m.label}</div>
                  <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.bestFor}</div>
                  <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
                    <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: ps.bg, color: ps.color, fontWeight: 500 }}>{m.provider}</span>
                    <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: "#FAEEDA", color: "#633806", fontWeight: 500 }}>Cost: {COST[m.costTier]}</span>
                    <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: "#F1EFE8", color: "#444441", fontWeight: 500 }}>{SPEED[m.speed]}</span>
                  </div>
                </div>
                {isSel && <span style={{ color: ps.dot, fontSize: 13, flexShrink: 0 }}>✓</span>}
              </div>
            );
          })}

          <div style={{ padding: "8px 13px", background: "#F7F6F2" }}>
            <div style={{ fontSize: 9, fontWeight: 500, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 5 }}>
              Council mode — select 2 or 3
            </div>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {MODELS.map(m => {
                const ps = PILL[m.provider];
                const isSel = selected.includes(m.id);
                return (
                  <div
                    key={m.id}
                    onClick={() => toggle(m.id)}
                    style={{
                      padding: "3px 8px", borderRadius: 12, fontSize: 10, fontWeight: 500,
                      cursor: "pointer", background: ps.bg, color: ps.color,
                      border: `0.5px solid ${isSel ? ps.dot : ps.border}`,
                      transition: "border-color 0.15s",
                    }}
                  >
                    {m.label.split(" ")[0]}{isSel ? " ✓" : ""}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function pillSendColor(selected: string[]): string {
  if (selected.length === 0) return "#378ADD";
  if (selected.length >= 2) return "#534AB7";
  return PILL[selected[0]]?.send ?? "#378ADD";
}
