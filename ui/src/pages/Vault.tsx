import { useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Upload, CheckCircle2, Clock, FileText, Database, AlertTriangle } from 'lucide-react'
import { getPipeline, confirmPipeline } from '../api'
import { useAppStore } from '../store'
import type { PipelineRow } from '../types'

const CLASSIFICATIONS = ['10_PUBLIC', '20_PROJECTS', '30_FINANCE', '40_PRIVATE', '50_SECRETS']

const TIER_COLORS: Record<string, string> = {
  '10_PUBLIC':   'bg-blue-500/20 text-blue-400',
  '20_PROJECTS': 'bg-emerald-500/20 text-emerald-400',
  '30_FINANCE':  'bg-amber-500/20 text-amber-400',
  '40_PRIVATE':  'bg-rose-500/20 text-rose-400',
  '50_SECRETS':  'bg-purple-500/20 text-purple-400',
}

const STAGE_ICONS: Record<string, typeof Clock> = {
  inbox:    Clock,
  confirmed: CheckCircle2,
  archived:  CheckCircle2,
  ingested:  Database,
  confirm_error: AlertTriangle,
}

export default function Vault() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const qc = useQueryClient()

  const [activeTab, setActiveTab] = useState<'pipeline' | 'upload' | 'ingest'>('pipeline')
  const [classification, setClassification] = useState('10_PUBLIC')
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const { data: pipeline = [] } = useQuery({
    queryKey: ['pipeline'],
    queryFn: getPipeline,
    refetchInterval: 30000,
  })

  const handleUpload = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setUploading(true)
    setUploadResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('classification', classification)
      const res = await fetch('/api/v1/vault/upload', { method: 'POST', body: fd })
      const data = await res.json()
      setUploadResult(`Uploaded: ${data.filename} → ${data.stage} (${data.size_bytes} bytes)`)
      qc.invalidateQueries({ queryKey: ['pipeline'] })
      if (fileRef.current) fileRef.current.value = ''
    } catch (e) {
      setUploadResult(`Error: ${e instanceof Error ? e.message : 'Upload failed'}`)
    } finally { setUploading(false) }
  }

  const handleConfirm = async (id: string) => {
    setConfirming(id)
    try {
      await confirmPipeline(id)
      qc.invalidateQueries({ queryKey: ['pipeline'] })
    } finally { setConfirming(null) }
  }

  const TABS = [
    { id: 'pipeline', label: 'Pipeline' },
    { id: 'upload',   label: 'Upload' },
    { id: 'ingest',   label: 'Ingest' },
  ] as const

  return (
    <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="max-w-4xl space-y-6">
      <div>
        <h1 className="font-serif italic text-3xl">Vault</h1>
        <p className="text-[10px] font-mono uppercase opacity-50 mt-1">Upload · classify · archive · ingest</p>
      </div>

      {/* Sub-tabs */}
      <div className={`flex gap-1 p-1 rounded-2xl border ${border} ${subtle} w-fit`}>
        {TABS.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 rounded-xl text-xs font-mono font-bold transition-all ${
              activeTab === tab.id
                ? isDark ? 'bg-white text-black' : 'bg-[#141414] text-white'
                : 'opacity-50 hover:opacity-80'
            }`}>{tab.label}</button>
        ))}
      </div>

      <AnimatePresence mode="wait">

        {/* PIPELINE TAB */}
        {activeTab === 'pipeline' && (
          <motion.div key="pipeline" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-3">
            {pipeline.length === 0 && (
              <div className={`p-8 rounded-2xl border ${border} text-center`}>
                <p className="text-sm opacity-40">No documents in pipeline</p>
              </div>
            )}
            {pipeline.map((row: PipelineRow) => {
              const Icon = STAGE_ICONS[row.stage] ?? Clock
              return (
                <motion.div key={row.id} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }}
                  className={`flex items-center gap-4 p-4 rounded-2xl border ${border} ${subtle}`}>
                  <FileText className="w-5 h-5 opacity-40 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold truncate">{row.filename}</p>
                    <p className="text-[10px] font-mono opacity-40">{row.content_type} · {(row.size_bytes / 1024).toFixed(1)} KB</p>
                  </div>
                  <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${TIER_COLORS['10_PUBLIC']}`}>
                    {row.stage}
                  </span>
                  <Icon className="w-4 h-4 opacity-40 flex-shrink-0" />
                  {row.stage === 'inbox' && (
                    <button
                      onClick={() => handleConfirm(row.id)}
                      disabled={confirming === row.id}
                      className={`px-3 py-1.5 rounded-xl text-xs font-mono font-bold border transition-all ${
                        confirming === row.id ? 'opacity-40' : isDark ? 'border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10' : 'border-[#141414]/20 hover:bg-[#141414]/5'
                      }`}
                    >
                      {confirming === row.id ? 'Archiving…' : 'Confirm'}
                    </button>
                  )}
                </motion.div>
              )
            })}
          </motion.div>
        )}

        {/* UPLOAD TAB */}
        {activeTab === 'upload' && (
          <motion.div key="upload" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-5">
            <div className={`p-6 rounded-2xl border ${border} ${subtle} space-y-4`}>
              <p className="text-[10px] font-mono uppercase opacity-40">Classification Tier</p>
              <div className="flex flex-wrap gap-2">
                {CLASSIFICATIONS.map(c => (
                  <button key={c} onClick={() => setClassification(c)}
                    className={`px-3 py-1.5 rounded-full text-xs font-mono font-bold border transition-all ${
                      classification === c
                        ? TIER_COLORS[c]
                        : `${border} opacity-40 hover:opacity-70`
                    }`}>{c}</button>
                ))}
              </div>
              <div className={`border-2 border-dashed ${border} rounded-2xl p-8 text-center space-y-3`}>
                <Upload className="w-8 h-8 opacity-30 mx-auto" />
                <p className="text-sm opacity-50">Select a file to upload</p>
                <input ref={fileRef} type="file" className="hidden" />
                <button onClick={() => fileRef.current?.click()}
                  className={`px-4 py-2 rounded-xl text-sm font-mono border ${border} hover:bg-white/5 transition-all`}>
                  Choose File
                </button>
              </div>
              <button onClick={handleUpload} disabled={uploading}
                className={`w-full py-3 rounded-xl text-sm font-bold transition-all disabled:opacity-40 ${isDark ? 'bg-emerald-500 text-[#0A0A0A]' : 'bg-[#141414] text-[#E4E3E0]'}`}>
                {uploading ? 'Uploading…' : 'Upload to Vault'}
              </button>
              {uploadResult && (
                <p className="text-xs font-mono opacity-60 text-center">{uploadResult}</p>
              )}
            </div>
          </motion.div>
        )}

        {/* INGEST TAB */}
        {activeTab === 'ingest' && (
          <motion.div key="ingest" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <div className={`p-6 rounded-2xl border ${border} ${subtle} space-y-4`}>
              <p className="text-[10px] font-mono uppercase opacity-40">Document Ingestion Pipeline</p>
              <div className="space-y-3">
                {[
                  { label: 'PDF → Text + Chunks', desc: 'Extract text, chunk, embed into pgvector', badge: 'PDF' },
                  { label: 'Excel → Database',    desc: 'Parse headers + rows, create table in jarvis_alpha', badge: 'XLS' },
                ].map(item => (
                  <div key={item.label} className={`p-4 rounded-xl border ${border} flex items-center gap-4`}>
                    <span className="text-[10px] font-mono px-2 py-1 rounded bg-indigo-500/20 text-indigo-400">{item.badge}</span>
                    <div className="flex-1">
                      <p className="text-sm font-bold">{item.label}</p>
                      <p className="text-[10px] opacity-40 mt-0.5">{item.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-[10px] font-mono opacity-30 text-center">
                Select a document from the Pipeline tab and use Confirm to trigger ingest
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
