import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Camera,
  ExternalLink,
  FileSearch,
  Globe2,
  Loader2,
  Network,
  Search,
  ShieldCheck,
} from 'lucide-react'
import { apiJson } from '../../lib/apiFetch'
import type {
  BeaconBrowserApprovalResponse,
  BeaconCrawlerExtractResponse,
  BeaconCrawlerMapResponse,
  BeaconCrawlerMode,
  BeaconCrawlerRenderResponse,
  BeaconCrawlerResult,
  BeaconCrawlerScrapeResponse,
} from '../../types/beacon'

const CRAWLER_MODES: Array<{
  key: BeaconCrawlerMode
  label: string
  detail: string
}> = [
  { key: 'scrape', label: 'Scrape', detail: 'one URL' },
  { key: 'map', label: 'Map', detail: 'same-host links' },
  { key: 'crawl', label: 'Crawl', detail: 'bounded pages' },
  { key: 'extract', label: 'Extract', detail: 'schema fields' },
  { key: 'render', label: 'Render', detail: 'approval first' },
]

export function BeaconCrawlerConsole({
  isDark,
  onComplete,
}: {
  isDark: boolean
  onComplete?: () => void
}) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const panel = isDark ? 'bg-white/5' : 'bg-white/50'
  const softPanel = isDark ? 'bg-black/15' : 'bg-white/35'
  const [mode, setMode] = useState<BeaconCrawlerMode>('scrape')
  const [url, setUrl] = useState('https://example.com/')
  const [query, setQuery] = useState('example domain')
  const [schemaText, setSchemaText] = useState('title: page title\nsummary: concise summary')
  const [maxPages, setMaxPages] = useState(2)
  const [maxDepth, setMaxDepth] = useState(1)
  const [approvalQueueId, setApprovalQueueId] = useState('')
  const [approval, setApproval] = useState<BeaconBrowserApprovalResponse | null>(null)
  const [result, setResult] = useState<BeaconCrawlerResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const selectedMode = useMemo(
    () => CRAWLER_MODES.find((item) => item.key === mode) ?? CRAWLER_MODES[0],
    [mode],
  )
  const parsedUrl = useMemo(() => parseCrawlerUrl(url), [url])
  const schema = useMemo(() => parseSchema(schemaText), [schemaText])
  const schemaFieldCount = Object.keys(schema).length
  const canRun = Boolean(url.trim() && parsedUrl.valid && !loading)
  const renderReadyToRun = mode === 'render' && Boolean(approvalQueueId.trim())

  const runCrawler = async () => {
    if (!canRun) return
    setLoading(true)
    setError('')
    try {
      if (mode === 'render' && !renderReadyToRun) {
        const payload = await apiJson<BeaconBrowserApprovalResponse>(
          '/v1/internet-scout/crawler/scrape/browser-approval-request',
          {
            method: 'POST',
            body: JSON.stringify(scrapeBody(url, query)),
          },
        )
        setApproval(payload)
        setApprovalQueueId(payload.approval_queue_id)
        setResult(null)
        onComplete?.()
        return
      }

      const payload = await runCrawlerMode(mode, {
        url,
        query,
        schema,
        maxPages,
        maxDepth,
        approvalQueueId,
      })
      setResult(payload)
      onComplete?.()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Crawler request failed')
    } finally {
      setLoading(false)
    }
  }

  const runLabel = mode === 'render'
    ? renderReadyToRun ? 'Run approved render' : 'Queue render approval'
    : `Run ${selectedMode.label.toLowerCase()}`

  return (
    <section className={`rounded-lg border p-4 ${border} ${panel}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Crawler console</p>
          <h2 className="mt-1 text-lg font-semibold">Scrape, map, crawl, extract, render</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          {['Cache first', 'Same host', 'No forms', 'No credentials'].map((item) => (
            <span key={item} className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
              {item}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-5">
            {CRAWLER_MODES.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-pressed={mode === item.key}
                onClick={() => {
                  setMode(item.key)
                  setError('')
                }}
                className={`min-h-11 rounded-lg border px-3 text-left text-xs transition ${border} ${
                  mode === item.key
                    ? 'border-emerald-500 bg-emerald-500 text-[#0A0A0A]'
                    : isDark ? 'hover:bg-white/10' : 'hover:bg-white/70'
                }`}
              >
                <span className="block font-semibold">{item.label}</span>
                <span className="block opacity-55">{item.detail}</span>
              </button>
            ))}
          </div>

          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(180px,240px)_auto]">
            <label className="relative min-w-0">
              <Globe2 className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 opacity-45" />
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://example.com/"
                className={`min-h-11 w-full rounded-lg border bg-transparent py-2 pl-10 pr-3 text-sm outline-none ${border}`}
              />
            </label>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Optional query"
              className={`min-h-11 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
            />
            <button
              type="button"
              onClick={runCrawler}
              disabled={!canRun}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-[#0A0A0A] transition hover:bg-emerald-400 disabled:opacity-45"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : modeIcon(mode)}
              {loading ? 'Running' : runLabel}
            </button>
          </div>

          {!parsedUrl.valid && <p className="text-xs text-rose-500">Enter a full http or https URL.</p>}
          {mode === 'render' && (
            <div className={`rounded-lg border px-3 py-2 text-xs ${border} ${softPanel}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="inline-flex items-center gap-2 font-semibold">
                  <ShieldCheck className="h-4 w-4 text-cyan-500" />
                  Browser render requires operator approval before execution.
                </span>
                <Link to="/approvals" className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
                  Review approvals
                </Link>
              </div>
              <input
                value={approvalQueueId}
                onChange={(event) => setApprovalQueueId(event.target.value)}
                placeholder="Approval queue id appears here after queueing"
                className={`mt-3 min-h-10 w-full rounded-lg border bg-transparent px-3 text-xs outline-none ${border}`}
              />
              {approval && (
                <p className="mt-2 font-mono text-[10px] uppercase opacity-55">
                  queued {approval.approval_queue_id.slice(0, 8)} · hosts {approval.preview.allowed_hosts.join(', ') || 'not reported'}
                </p>
              )}
            </div>
          )}
        </div>

        <details className={`rounded-lg border p-3 text-xs ${border} ${softPanel}`}>
          <summary className="cursor-pointer font-semibold">Caps and schema</summary>
          <div className="mt-3 grid gap-3">
            <label>
              <span className="text-[10px] font-mono uppercase tracking-widest opacity-45">Max pages</span>
              <input
                type="number"
                min={1}
                max={10}
                value={maxPages}
                onChange={(event) => setMaxPages(clampNumber(event.target.value, 1, 10))}
                className={`mt-1 min-h-10 w-full rounded-lg border bg-transparent px-3 outline-none ${border}`}
              />
            </label>
            <label>
              <span className="text-[10px] font-mono uppercase tracking-widest opacity-45">Max depth</span>
              <input
                type="number"
                min={0}
                max={2}
                value={maxDepth}
                onChange={(event) => setMaxDepth(clampNumber(event.target.value, 0, 2))}
                className={`mt-1 min-h-10 w-full rounded-lg border bg-transparent px-3 outline-none ${border}`}
              />
            </label>
            <label>
              <span className="text-[10px] font-mono uppercase tracking-widest opacity-45">Extract schema</span>
              <textarea
                value={schemaText}
                onChange={(event) => setSchemaText(event.target.value)}
                rows={3}
                className={`mt-1 w-full resize-y rounded-lg border bg-transparent p-3 outline-none ${border}`}
              />
            </label>
            <p className="font-mono text-[10px] uppercase opacity-55">{schemaFieldCount} fields parsed</p>
          </div>
        </details>
      </div>

      {error && <p className="mt-3 text-sm text-rose-500">{error}</p>}
      {result && (
        <CrawlerResult result={result} mode={mode} isDark={isDark} />
      )}
    </section>
  )
}

async function runCrawlerMode(
  mode: BeaconCrawlerMode,
  options: {
    url: string
    query: string
    schema: Record<string, string>
    maxPages: number
    maxDepth: number
    approvalQueueId: string
  },
): Promise<BeaconCrawlerResult> {
  if (mode === 'scrape') {
    return await apiJson<BeaconCrawlerScrapeResponse>('/v1/internet-scout/crawler/scrape', {
      method: 'POST',
      body: JSON.stringify(scrapeBody(options.url, options.query)),
    })
  }
  if (mode === 'extract') {
    return await apiJson<BeaconCrawlerExtractResponse>('/v1/internet-scout/crawler/extract', {
      method: 'POST',
      body: JSON.stringify({
        ...scrapeBody(options.url, options.query),
        schema: options.schema,
      }),
    })
  }
  if (mode === 'render') {
    return await apiJson<BeaconCrawlerRenderResponse>('/v1/internet-scout/crawler/scrape/browser-run-approved', {
      method: 'POST',
      body: JSON.stringify({
        approval_queue_id: options.approvalQueueId.trim(),
        scrape: scrapeBody(options.url, options.query),
        max_steps: 5,
      }),
    })
  }

  const endpoint = mode === 'map' ? '/v1/internet-scout/crawler/map' : '/v1/internet-scout/crawler/crawl'
  return await apiJson<BeaconCrawlerMapResponse>(endpoint, {
    method: 'POST',
    body: JSON.stringify({
      url: options.url.trim(),
      max_pages: options.maxPages,
      max_depth: options.maxDepth,
      max_bytes: 200_000,
    }),
  })
}

function scrapeBody(url: string, query: string): { url: string; query?: string; max_bytes: number } {
  const trimmedQuery = query.trim()
  return {
    url: url.trim(),
    ...(trimmedQuery ? { query: trimmedQuery } : {}),
    max_bytes: 200_000,
  }
}

function CrawlerResult({
  result,
  mode,
  isDark,
}: {
  result: BeaconCrawlerResult
  mode: BeaconCrawlerMode
  isDark: boolean
}) {
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const softPanel = isDark ? 'bg-black/15' : 'bg-white/35'
  const host = 'host' in result ? result.host : result.seed_host
  const title = 'title' in result ? result.title : null
  const canonicalUrl = 'canonical_url' in result ? result.canonical_url : result.seed_url
  const cacheLabel = 'cache_hit' in result ? result.cache_hit ? 'cache hit' : 'cache miss' : 'map cache n/a'
  const countLabel = resultCountLabel(result)

  return (
    <div className={`mt-4 rounded-lg border p-3 ${border} ${softPanel}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Result summary</p>
          <p className="mt-1 truncate text-sm font-semibold">{title || host}</p>
          <a
            href={canonicalUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-1 inline-flex max-w-full items-center gap-1 truncate text-xs opacity-65 hover:opacity-100"
          >
            <ExternalLink className="h-3 w-3 shrink-0" />
            <span className="truncate">{canonicalUrl}</span>
          </a>
        </div>
        <div className="flex flex-wrap gap-2">
          {[mode, cacheLabel, countLabel].map((item) => (
            <span key={item} className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
              {item}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-4">
        <ResultMetric label="Request" value={result.request_id.slice(0, 8)} />
        <ResultMetric label="Host" value={host} />
        <ResultMetric label="Fetched" value={'fetched_at' in result ? formatCrawlerDate(result.fetched_at) : `${result.page_count} pages`} />
        <ResultMetric label="Trust boundary" value={result.raw_web_content_is_untrusted ? 'untrusted web content' : 'trusted'} />
      </div>

      <div className="mt-3 grid gap-2 lg:grid-cols-2">
        {isScrapeResult(result) && (
          <details className={`rounded-lg border p-3 ${border}`}>
            <summary className="cursor-pointer text-sm font-semibold">Text excerpt and links</summary>
            <p className="mt-3 line-clamp-6 whitespace-pre-wrap text-sm leading-6 opacity-75">{result.text || 'No text returned.'}</p>
            <LinkList links={result.links} border={border} />
          </details>
        )}

        {isMapResult(result) && (
          <details className={`rounded-lg border p-3 ${border}`}>
            <summary className="cursor-pointer text-sm font-semibold">Pages and same-host links</summary>
            <div className="mt-3 space-y-2">
              {result.pages.map((page) => (
                <div key={page.url} className={`rounded border p-2 text-xs ${border}`}>
                  <p className="truncate font-semibold">{page.url}</p>
                  <p className="mt-1 font-mono text-[10px] uppercase opacity-55">
                    d{page.depth} · HTTP {page.status_code} · {page.links.length} links
                  </p>
                </div>
              ))}
            </div>
            <LinkList links={result.links} border={border} />
          </details>
        )}

        {isExtractResult(result) && (
          <details className={`rounded-lg border p-3 ${border}`}>
            <summary className="cursor-pointer text-sm font-semibold">Fields and evidence</summary>
            <div className="mt-3 space-y-2">
              {result.fields.map((field) => (
                <div key={field.field} className={`rounded border p-2 text-xs ${border}`}>
                  <p className="font-semibold">
                    {field.field}: {field.found ? field.value || 'found' : 'not found'}
                  </p>
                  {field.evidence_text && <p className="mt-1 line-clamp-3 opacity-65">{field.evidence_text}</p>}
                </div>
              ))}
            </div>
          </details>
        )}

        {isRenderResult(result) && (
          <details className={`rounded-lg border p-3 ${border}`}>
            <summary className="cursor-pointer text-sm font-semibold">Render evidence</summary>
            <div className="mt-3 grid gap-2 text-xs">
              <ResultMetric label="Approval" value={result.approval_queue_id.slice(0, 8)} />
              <ResultMetric label="Screenshot" value={result.screenshot_ref || 'not returned'} />
              <ResultMetric label="Evidence path" value={result.evidence_path} />
              <ResultMetric label="Audit path" value={result.audit_path} />
              <ResultMetric label="Audit rows" value={String(result.action_audit_count)} />
            </div>
          </details>
        )}
      </div>
    </div>
  )
}

function ResultMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">{label}</p>
      <p className="mt-1 truncate font-semibold">{value}</p>
    </div>
  )
}

function LinkList({ links, border }: { links: string[]; border: string }) {
  if (links.length === 0) return null
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {links.slice(0, 12).map((link) => (
        <a
          key={link}
          href={link}
          target="_blank"
          rel="noreferrer"
          className={`max-w-full truncate rounded border px-2 py-1 text-xs opacity-70 hover:opacity-100 ${border}`}
        >
          {link}
        </a>
      ))}
    </div>
  )
}

function parseSchema(value: string): Record<string, string> {
  return value.split('\n').reduce<Record<string, string>>((schema, line) => {
    const [rawField, ...rest] = line.split(':')
    const field = rawField.trim()
    if (!field) return schema
    schema[field] = rest.join(':').trim() || field
    return schema
  }, {})
}

function parseCrawlerUrl(value: string): { valid: boolean; host: string } {
  if (!value.trim()) return { valid: true, host: '' }
  try {
    const parsed = new URL(value.trim())
    const valid = parsed.protocol === 'https:' || parsed.protocol === 'http:'
    return { valid, host: valid ? parsed.host.toLowerCase() : '' }
  } catch {
    return { valid: false, host: '' }
  }
}

function clampNumber(value: string, min: number, max: number): number {
  const parsed = Number.parseInt(value, 10)
  if (Number.isNaN(parsed)) return min
  return Math.min(max, Math.max(min, parsed))
}

function modeIcon(mode: BeaconCrawlerMode) {
  if (mode === 'map' || mode === 'crawl') return <Network className="h-4 w-4" />
  if (mode === 'extract') return <FileSearch className="h-4 w-4" />
  if (mode === 'render') return <Camera className="h-4 w-4" />
  return <Search className="h-4 w-4" />
}

function resultCountLabel(result: BeaconCrawlerResult): string {
  if ('fields' in result) return `${result.fields.length} fields`
  if ('page_count' in result) return `${result.page_count} pages · ${result.link_count} links`
  return `${result.links.length} links`
}

function isScrapeResult(result: BeaconCrawlerResult): result is BeaconCrawlerScrapeResponse | BeaconCrawlerRenderResponse {
  return 'text' in result && 'canonical_url' in result
}

function isMapResult(result: BeaconCrawlerResult): result is BeaconCrawlerMapResponse {
  return 'pages' in result
}

function isExtractResult(result: BeaconCrawlerResult): result is BeaconCrawlerExtractResponse {
  return 'fields' in result
}

function isRenderResult(result: BeaconCrawlerResult): result is BeaconCrawlerRenderResponse {
  return 'audit_path' in result
}

function formatCrawlerDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}
