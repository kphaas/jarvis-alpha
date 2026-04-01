import { motion } from 'framer-motion'
import { useAppStore } from '../store'

interface Props { label: string; phase: string }

export default function Placeholder({ label, phase }: Props) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
      className={`p-10 rounded-2xl border ${border} ${subtle} text-center space-y-3`}
    >
      <h1 className="font-serif italic text-3xl">{label}</h1>
      <p className="text-[10px] font-mono uppercase opacity-40">{phase}</p>
    </motion.div>
  )
}
