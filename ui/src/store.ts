import { create } from "zustand"

interface AppState {
  userId: string
  sessionId: string
  mode: string
  workspaceId: string | null
  persistent: boolean
  setMode: (mode: string) => void
  setPersistent: (v: boolean) => void
  setWorkspaceId: (id: string | null) => void
}

export const useAppStore = create<AppState>((set) => ({
  userId: "ken",
  sessionId: crypto.randomUUID(),
  mode: "auto",
  workspaceId: null,
  persistent: false,
  setMode: (mode) => set({ mode }),
  setPersistent: (persistent) => set({ persistent }),
  setWorkspaceId: (workspaceId) => set({ workspaceId }),
}))
