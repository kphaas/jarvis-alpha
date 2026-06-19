import { useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ExternalLink } from 'lucide-react'
import { useAppStore } from '../store'
import { SPACES, getSpaceBySlug } from '../lib/spaces'

export default function Space() {
  const { slug } = useParams<{ slug: string }>()
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  const space = getSpaceBySlug(slug)
  const tabs = space?.tabs ?? []
  const label = space?.label ?? slug ?? 'Space'
  const summary = space?.summary ?? 'Protected AT0 domain workspace.'
  const status = space?.status ?? 'Private workspace'

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <div>
        <h1 className="font-serif italic text-3xl">{label}</h1>
        <p className="text-[10px] font-mono uppercase opacity-50 mt-1">{status} · PIN protected</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {tabs.map(tab => (
          <div key={tab} className={`px-4 py-2 rounded-xl border ${border} ${subtle} text-sm opacity-60`}>
            {tab}
          </div>
        ))}
      </div>
      <div className={`rounded-lg border ${border} p-5`}>
        <p className="text-sm opacity-70">{summary}</p>
      </div>
      <div className="space-y-3">
        <div className="flex items-end justify-between gap-4">
          <h2 className="text-sm font-semibold uppercase tracking-[0.18em] opacity-50">Domain links</h2>
          <p className="text-[10px] font-mono uppercase opacity-40">{SPACES.length} spaces</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {SPACES.map(item => {
            const isActive = item.slug === space?.slug
            return (
              <a
                key={item.slug}
                href={item.launchUrl}
                target="_blank"
                rel="noreferrer"
                className={`rounded-lg border p-4 transition-all ${
                  isActive
                    ? isDark ? 'border-emerald-400 bg-emerald-400/10' : 'border-[#141414] bg-[#141414]/10'
                    : `${border} ${subtle}`
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold">{item.label}</p>
                  <span className="inline-flex items-center gap-1 text-[9px] font-mono uppercase opacity-50">
                    <ExternalLink className="h-3 w-3" />
                    Open
                  </span>
                </div>
                <p className="mt-2 text-xs leading-5 opacity-55">{item.summary}</p>
                <p className="mt-3 text-[10px] font-mono uppercase opacity-40">{item.launchLabel}</p>
              </a>
            )
          })}
        </div>
      </div>
    </motion.div>
  )
}
