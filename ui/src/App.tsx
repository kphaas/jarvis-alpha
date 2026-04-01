import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import Dashboard from "./pages/Dashboard"
import Ask from "./pages/Ask"
import Vault from "./pages/Vault"
import Space from "./pages/Space"

const qc = new QueryClient({
  defaultOptions: { queries: { staleTime: 15 * 60 * 1000 } },
})

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/ask", label: "Ask" },
  { to: "/vault", label: "Vault" },
]

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
          <nav className="flex items-center gap-6 px-6 py-3 bg-gray-900 border-b border-gray-800">
            <span className="font-bold text-indigo-400 tracking-widest text-sm">JARVIS ALPHA</span>
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                className={({ isActive }) =>
                  `text-sm font-medium ${isActive ? "text-white" : "text-gray-400 hover:text-white"}`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <main className="flex-1 p-6">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/ask" element={<Ask />} />
              <Route path="/vault" element={<Vault />} />
              <Route path="/space/:slug" element={<Space />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
