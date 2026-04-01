import { useQuery } from "@tanstack/react-query"
import { getHealth } from "../api"

export default function Dashboard() {
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: getHealth, refetchInterval: 60000 })

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      <section>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">Service Map</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {["brain", "gateway", "endpoint", "sandbox"].map((node) => (
            <div key={node} className="bg-gray-900 rounded-lg p-4 border border-gray-800">
              <div className="flex items-center gap-2 mb-1">
                <span className={`w-2 h-2 rounded-full ${node === "brain" && health?.status === "ok" ? "bg-green-400" : "bg-gray-600"}`} />
                <span className="text-sm font-medium capitalize">{node}</span>
              </div>
              <p className="text-xs text-gray-500">{node === "brain" ? health?.status ?? "checking…" : "pending"}</p>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">Timeline</h2>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 text-sm text-gray-500">
          Timeline feed — wired next session
        </div>
      </section>

      <section>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">Metrics</h2>
        <div className="grid grid-cols-3 gap-4">
          {["Cost Today", "Requests", "Vault Docs"].map((label) => (
            <div key={label} className="bg-gray-900 rounded-lg p-4 border border-gray-800">
              <p className="text-xs text-gray-500 mb-1">{label}</p>
              <p className="text-2xl font-bold">—</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
