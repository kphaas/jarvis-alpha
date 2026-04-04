import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout } from './components/Layout'
import { PinGate } from './components/PinGate'
import { useAppStore } from './store'
import { Suspense, lazy } from 'react'

const Home = lazy(() => import('./pages/Home'))
const Ask = lazy(() => import('./pages/Ask'))
const Vault = lazy(() => import('./pages/Vault'))
const Space = lazy(() => import('./pages/Space'))
const Placeholder = lazy(() => import('./pages/Placeholder'))
const CostCenter = lazy(() => import('./pages/CostCenter'))
const Health = lazy(() => import('./pages/Health'))
const Mesh = lazy(() => import('./pages/Mesh'))
const Approvals = lazy(() => import('./pages/Approvals'))
const Security = lazy(() => import('./pages/Security'))

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
            <Suspense fallback={<div className="flex items-center justify-center h-screen text-zinc-500">Loading...</div>}>
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
              <Route path="/approvals"  element={<Approvals />} />
              <Route path="/security"   element={<Security />} />
              <Route path="/governance" element={<Placeholder label="Governance"  phase="Next session" />} />
              <Route path="/cost"       element={<Navigate to="/costs" replace />} />
              <Route path="/costs"      element={<CostCenter />} />
              <Route path="/documents"  element={<Placeholder label="Documents"   phase="Next session" />} />
              <Route path="/settings"   element={<Placeholder label="Settings"    phase="Next session" />} />
            </Routes>
              </Suspense>
          </Layout>
        </BrowserRouter>
      </QueryClientProvider>
    </PinGate>
  )
}
