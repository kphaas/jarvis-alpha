import { useRef } from "react";

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


export interface ModelSelectorProps {
  selected: string[];
  onChange: (ids: string[]) => void;
}

export function ModelSelector({ selected, onChange }: ModelSelectorProps) {
  const ref = useRef<HTMLDivElement>(null);

  function toggle(id: string) {
    if (id === "auto") { onChange([]); return; }
    if (selected.includes(id)) {
      onChange(selected.filter(s => s !== id));
    } else if (selected.length < 3) {
      onChange([...selected, id]);
    }
  }

  const isAuto = selected.length === 0;

  return (
    <div ref={ref} style={{
      display: "flex", alignItems: "center",
      background: "var(--color-background-secondary)",
      border: "0.5px solid var(--color-border-secondary)",
      borderRadius: 10, padding: 2, gap: 1,
    }}>
      {/* Auto segment */}
      <button
        onClick={() => onChange([])}
        style={{
          padding: "4px 10px", borderRadius: 8, fontSize: 11, fontWeight: isAuto ? 600 : 400,
          background: isAuto ? PILL["auto"].bg : "transparent",
          border: isAuto ? `0.5px solid ${PILL["auto"].border}` : "0.5px solid transparent",
          color: isAuto ? PILL["auto"].color : "var(--color-text-tertiary)",
          cursor: "pointer", fontFamily: "var(--font-sans)",
          transition: "all 0.15s",
          whiteSpace: "nowrap",
        }}
      >Auto</button>

      {/* Model segments */}
      {MODELS.map(m => {
        const ps    = PILL[m.provider];
        const isSel = selected.includes(m.id);
        const ICONS: Record<string, string> = {
          local: "⚡", claude: "◈", perplexity: "◎", gemini: "✦",
        };
        return (
          <button
            key={m.id}
            onClick={() => toggle(m.id)}
            title={m.bestFor}
            style={{
              padding: "4px 10px", borderRadius: 8, fontSize: 11, fontWeight: isSel ? 600 : 400,
              background: isSel ? ps.bg : "transparent",
              border: isSel ? `0.5px solid ${ps.border}` : "0.5px solid transparent",
              color: isSel ? ps.color : "var(--color-text-tertiary)",
              cursor: "pointer", fontFamily: "var(--font-sans)",
              display: "flex", alignItems: "center", gap: 4,
              transition: "all 0.15s",
              whiteSpace: "nowrap",
            }}
          >
            <span style={{ fontSize: 10 }}>{ICONS[m.id]}</span>
            {m.label.split(" ")[0]}
          </button>
        );
      })}
    </div>
  );
}

export function pillSendColor(selected: string[]): string {
  if (selected.length === 0) return "#378ADD";
  if (selected.length >= 2) return "#534AB7";
  return PILL[selected[0]]?.send ?? "#378ADD";
}
