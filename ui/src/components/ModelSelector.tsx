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
  { id: "local",      label: "Local (Llama)",  provider: "local",      costTier: "free",   speed: "fast",   bestFor: "Quick answers, code snippets" },
  { id: "claude",     label: "Claude Sonnet",  provider: "claude",     costTier: "medium", speed: "medium", bestFor: "Reasoning, architecture, planning" },
  { id: "perplexity", label: "Perplexity",     provider: "perplexity", costTier: "low",    speed: "fast",   bestFor: "Web search, current events, research" },
  { id: "gemini",     label: "Gemini Flash",   provider: "gemini",     costTier: "low",    speed: "fast",   bestFor: "Structured output, long context" },
];

const PROVIDER_COLOR: Record<string, { color: string; bg: string }> = {
  local:      { color: "#444441", bg: "#F1EFE8" },
  claude:     { color: "#3C3489", bg: "#EEEDFE" },
  perplexity: { color: "#27500A", bg: "#EAF3DE" },
  gemini:     { color: "#633806", bg: "#FAEEDA" },
};

const COST_LABEL: Record<string, string> = { free: "$0", low: "$", medium: "$$", high: "$$$" };
const SPEED_LABEL: Record<string, string> = { fast: "Fast", medium: "Moderate", slow: "Slow" };

interface Props {
  selected: string[];
  onChange: (ids: string[]) => void;
}

export function ModelSelector({ selected, onChange }: Props) {
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
    const next = selected.includes(id) ? selected.filter(s => s !== id) : [...selected.filter(s => s !== "auto"), id].slice(0, 3);
    onChange(next);
  }

  const isAuto = selected.length === 0;
  const isCouncil = selected.length >= 2;
  const displayLabel = isAuto ? "AUTO" : isCouncil ? `Council (${selected.length})` : MODELS.find(m => m.id === selected[0])?.label ?? selected[0];

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
      <button onClick={() => setOpen(o => !o)} style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "5px 10px", border: "0.5px solid var(--color-border-secondary)",
        borderRadius: "var(--border-radius-md)", background: "var(--color-background-secondary)",
        cursor: "pointer", fontSize: 12, fontWeight: 500, color: "var(--color-text-primary)",
        fontFamily: "var(--font-sans)",
      }}>
        {isCouncil && <span style={{ fontSize: 11, color: "#534AB7" }}>⟐</span>}
        {displayLabel}
        <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>▾</span>
      </button>

      {open && (
        <div style={{
          position: "absolute", bottom: "calc(100% + 6px)", left: 0, zIndex: 100,
          background: "var(--color-background-primary)", border: "0.5px solid var(--color-border-secondary)",
          borderRadius: "var(--border-radius-lg)", width: 280, boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
          overflow: "hidden",
        }}>
          <div style={{ padding: "8px 12px", borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
            <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginBottom: 6 }}>Select up to 3 for council mode</div>
            <div
              onClick={() => toggle("auto")}
              style={{
                padding: "7px 10px", borderRadius: "var(--border-radius-md)", cursor: "pointer",
                background: isAuto ? "#E6F1FB" : "transparent",
                border: isAuto ? "0.5px solid #378ADD" : "0.5px solid transparent",
                display: "flex", alignItems: "center", justifyContent: "space-between",
              }}
            >
              <div>
                <div style={{ fontSize: 13, fontWeight: 500, color: isAuto ? "#0C447C" : "var(--color-text-primary)" }}>AUTO</div>
                <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>JARVIS picks based on complexity</div>
              </div>
              {isAuto && <span style={{ color: "#378ADD", fontSize: 14 }}>✓</span>}
            </div>
          </div>

          <div style={{ padding: 8 }}>
            {MODELS.map(m => {
              const isSelected = selected.includes(m.id);
              const pc = PROVIDER_COLOR[m.provider];
              return (
                <div key={m.id} onClick={() => toggle(m.id)} style={{
                  padding: "8px 10px", borderRadius: "var(--border-radius-md)", cursor: "pointer",
                  background: isSelected ? pc.bg : "transparent",
                  border: isSelected ? `0.5px solid ${pc.color}30` : "0.5px solid transparent",
                  marginBottom: 2, display: "flex", alignItems: "flex-start", justifyContent: "space-between",
                }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                      <span style={{ fontSize: 13, fontWeight: 500, color: isSelected ? pc.color : "var(--color-text-primary)" }}>{m.label}</span>
                      <span style={{ fontSize: 10, padding: "1px 5px", borderRadius: 3, background: pc.bg, color: pc.color }}>{m.provider}</span>
                    </div>
                    <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{m.bestFor}</div>
                    <div style={{ display: "flex", gap: 8, marginTop: 3 }}>
                      <span style={{ fontSize: 10, color: "var(--color-text-secondary)" }}>Cost: {COST_LABEL[m.costTier]}</span>
                      <span style={{ fontSize: 10, color: "var(--color-text-secondary)" }}>Speed: {SPEED_LABEL[m.speed]}</span>
                    </div>
                  </div>
                  {isSelected && <span style={{ color: pc.color, fontSize: 14, marginLeft: 8 }}>✓</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
