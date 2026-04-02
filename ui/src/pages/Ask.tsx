import { useState, useCallback } from "react";
import { ThreadSidebar, type Thread } from "../components/ThreadSidebar";
import { ChatWindow } from "../components/ChatWindow";
import { ModelSelector } from "../components/ModelSelector";
import { apiJson } from "../lib/apiFetch";

export default function Ask() {
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [activeTitle, setActiveTitle]       = useState("New conversation");
  const [editingTitle, setEditingTitle]     = useState(false);
  const [titleInput, setTitleInput]         = useState("");
  const [sidebarTick, setSidebarTick]       = useState(0);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);

  function refreshSidebar() { setSidebarTick(t => t + 1); }

  const handleSelectThread = useCallback((t: Thread) => {
    setActiveThreadId(t.id);
    setActiveTitle(t.title);
  }, []);

  const handleNewThread = useCallback(() => {
    setActiveThreadId(null);
    setActiveTitle("New conversation");
  }, []);

  const handleThreadCreated = useCallback((id: string) => {
    setActiveThreadId(id);
    refreshSidebar();
    setTimeout(refreshSidebar, 2000);
  }, []);

  async function handleTitleSave() {
    if (!activeThreadId || !titleInput.trim()) { setEditingTitle(false); return; }
    try {
      await apiJson(`/v1/threads/${activeThreadId}`, {
        method: "PATCH",
        body: JSON.stringify({ title: titleInput.trim() }),
      });
      setActiveTitle(titleInput.trim());
      refreshSidebar();
    } catch {}
    setEditingTitle(false);
  }

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      <ThreadSidebar
        activeId={activeThreadId}
        onSelect={handleSelectThread}
        onNew={handleNewThread}
        refreshTick={sidebarTick}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <div style={{
          padding: "9px 14px",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
          display: "flex", alignItems: "center", gap: 8,
          background: "var(--color-background-primary)", flexShrink: 0,
        }}>
          {editingTitle ? (
            <input
              autoFocus value={titleInput}
              onChange={e => setTitleInput(e.target.value)}
              onBlur={handleTitleSave}
              onKeyDown={e => { if (e.key === "Enter") handleTitleSave(); if (e.key === "Escape") setEditingTitle(false); }}
              style={{
                flex: 1, fontSize: 13, fontWeight: 500,
                border: "none", borderBottom: "1px solid var(--color-border-secondary)",
                background: "transparent", outline: "none",
                fontFamily: "var(--font-sans)", color: "var(--color-text-primary)",
              }}
            />
          ) : (
            <span
              style={{ flex: 1, fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)", cursor: "text" }}
              onDoubleClick={() => { setTitleInput(activeTitle); setEditingTitle(true); }}
            >
              {activeTitle}
            </span>
          )}
          <svg
            width="12" height="12" viewBox="0 0 16 16" fill="none"
            stroke="var(--color-text-tertiary)" strokeWidth="1.5"
            style={{ cursor: "pointer", opacity: 0.4, flexShrink: 0 }}
            onClick={() => { setTitleInput(activeTitle); setEditingTitle(true); }}
          >
            <path d="M11 2L14 5L5 14H2V11L11 2Z"/>
          </svg>
          <ModelSelector selected={selectedModels} onChange={setSelectedModels} />
        </div>

        <ChatWindow
          threadId={activeThreadId}
          selectedModels={selectedModels}
          onThreadCreated={handleThreadCreated}
          onEscalated={refreshSidebar}
        />
      </div>
    </div>
  );
}
