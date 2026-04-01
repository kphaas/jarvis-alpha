import { useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAppStore } from '../store'

const SPACE_TABS: Record<string, string[]> = {
  familyvault: ['Family', 'Finance', 'Legal', 'Home Automation', 'Calendar', 'Personal Assistant', 'Life Automation'],
}

export default function Space() {
  const { slug } = useParams<{ slug: string }>()
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  const tabs = SPACE_TABS[slug ?? ''] ?? []
  const label = slug === 'familyvault' ? 'Family Vault' : slug ?? 'Space'

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <div>
        <h1 className="font-serif italic text-3xl">{label}</h1>
        <p className="text-[10px] font-mono uppercase opacity-50 mt-1">Private workspace · PIN protected</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {tabs.map(tab => (
          <div key={tab} className={`px-4 py-2 rounded-xl border ${border} ${subtle} text-sm opacity-60`}>
            {tab}
          </div>
        ))}
      </div>
      <div className={`p-8 rounded-2xl border ${border} text-center`}>
        <p className="text-sm opacity-40">Space content — wired next session</p>
      </div>
    </motion.div>
  )
}
