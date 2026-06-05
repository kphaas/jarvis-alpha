import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout } from './components/Layout'
import { PinGate } from './components/PinGate'
import { ErrorBoundary } from './components/shared'
import { useAppStore } from './store'
import { Suspense, lazy } from 'react'

const Home = lazy(() => import('./pages/Home'))
const Ask = lazy(() => import('./pages/Ask'))
const Vault = lazy(() => import('./pages/Vault'))
const Space = lazy(() => import('./pages/Space'))
const Placeholder = lazy(() => import('./pages/Placeholder'))
const Settings = lazy(() => import('./pages/Settings'))
const CostCenter = lazy(() => import('./pages/CostCenter'))
const Health = lazy(() => import('./pages/Health'))
const Errors = lazy(() => import('./pages/Errors'))
const Mesh = lazy(() => import('./pages/Mesh'))
const Approvals = lazy(() => import('./pages/Approvals'))
const Security = lazy(() => import('./pages/Security'))
const Agents = lazy(() => import('./pages/Agents'))
const Skills = lazy(() => import('./pages/Skills'))
const Governance = lazy(() => import('./pages/Governance'))
const Briefing = lazy(() => import('./pages/Briefing'))
const BriefingDetail = lazy(() => import('./pages/BriefingDetail'))

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 15 * 60 * 1000, retry: 1 } },
})

export default function App() {
  const { theme } = useAppStore()
  return (
    <PinGate>
      <QueryClientProvider client={qc}>
        <BrowserRouter>
          <Layout theme={theme}>
            <ErrorBoundary>
              <Suspense fallback={<div className="flex items-center justify-center h-screen text-zinc-500">Loading...</div>}>
                <Routes>
                  <Route path="/" element={<Home />} />
                  <Route path="/ask" element={<Ask />} />
                  <Route path="/vault" element={<Vault />} />
                  <Route path="/space/:slug" element={<Space />} />
                  <Route path="/briefing" element={<Briefing />} />
                  <Route path="/briefings/:batchRunId" element={<BriefingDetail />} />
                  <Route path="/mesh" element={<Mesh theme={theme} />} />
                  <Route path="/health" element={<Health theme={theme} />} />
                  <Route path="/errors" element={<Errors theme={theme} />} />
                  <Route path="/agents" element={<Agents />} />
                  <Route path="/skills" element={<Skills />} />
                  <Route path="/ops" element={<Placeholder label="Ops" phase="Next session" />} />
                  <Route path="/approvals" element={<Approvals />} />
                  <Route path="/security" element={<Security />} />
                  <Route path="/governance" element={<Governance />} />
                  <Route path="/cost" element={<Navigate to="/costs" replace />} />
                  <Route path="/costs" element={<CostCenter />} />
                  <Route path="/documents" element={<Placeholder label="Documents" phase="Next session" />} />
                  <Route path="/settings" element={<Settings />} />
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </Layout>
        </BrowserRouter>
      </QueryClientProvider>
    </PinGate>
  )
}
