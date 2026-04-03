import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout } from './components/Layout'
import { PinGate } from './components/PinGate'
import { useAppStore } from './store'
import Home from './pages/Home'
import Ask from './pages/Ask'
import Vault from './pages/Vault'
import Space from './pages/Space'
import Placeholder from './pages/Placeholder'
import CostCenter from './pages/CostCenter'
import Health from './pages/Health'
import Mesh from './pages/Mesh'

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 15 * 60 * 1000, retry: 1 } },
})

const brainToken = (import.meta.env.VITE_BRAIN_TOKEN as string) || ''

export default function App() {
  const { theme } = useAppStore()
  return (
    <PinGate>
      <QueryClientProvider client={qc}>
        <BrowserRouter>
          <Layout theme={theme}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/ask" element={<Ask />} />
              <Route path="/vault" element={<Vault />} />
              <Route path="/space/:slug" element={<Space />} />
              <Route path="/briefing"   element={<Placeholder label="Briefing"    phase="Next session" />} />
              <Route path="/mesh"       element={<Mesh theme={theme} token={brainToken} />} />
              <Route path="/health"     element={<Health theme={theme} token={brainToken} />} />
              <Route path="/errors"     element={<Placeholder label="Errors & Logs" phase="Next session" />} />
              <Route path="/agents"     element={<Placeholder label="Agents"      phase="Next session" />} />
              <Route path="/ops"        element={<Placeholder label="Ops"         phase="Next session" />} />
              <Route path="/security"   element={<Placeholder label="Security"    phase="Next session" />} />
              <Route path="/governance" element={<Placeholder label="Governance"  phase="Next session" />} />
              <Route path="/cost"       element={<Navigate to="/costs" replace />} />
              <Route path="/costs"      element={<CostCenter />} />
              <Route path="/documents"  element={<Placeholder label="Documents"   phase="Next session" />} />
              <Route path="/settings"   element={<Placeholder label="Settings"    phase="Next session" />} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </QueryClientProvider>
    </PinGate>
  )
}
