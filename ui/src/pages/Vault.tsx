import { useQuery } from "@tanstack/react-query"
import { getPipeline } from "../api"

export default function Vault() {
  const { data: pipeline = [] } = useQuery({ queryKey: ["pipeline"], queryFn: getPipeline, refetchInterval: 30000 })

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Vault</h1>
      <section>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3">Pipeline Inbox</h2>
        <div className="space-y-2">
          {pipeline.length === 0 && <p className="text-sm text-gray-500">No documents in pipeline.</p>}
          {pipeline.map((row: Record<string, unknown>) => (
            <div key={String(row.id)} className="bg-gray-900 border border-gray-800 rounded-lg p-3 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">{String(row.filename)}</p>
                <p className="text-xs text-gray-500">{String(row.content_type)} · {String(row.size_bytes)} bytes</p>
              </div>
              <span className="text-xs px-2 py-0.5 bg-gray-800 rounded-full text-gray-400">{String(row.stage)}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
