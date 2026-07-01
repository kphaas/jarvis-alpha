import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  Camera,
  Download,
  ExternalLink,
  FileSearch,
  Globe2,
  Loader2,
  Network,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react'
import { apiJson } from '../../lib/apiFetch'
import type {
  BeaconBrowserApprovalResponse,
  BeaconCrawlerBatchScrapeResponse,
  BeaconCrawlerExtractResponse,
  BeaconCrawlerMapResponse,
  BeaconCrawlerMode,
  BeaconCrawlerRenderResponse,
  BeaconCrawlerResult,
  BeaconCrawlerScrapeResponse,
  BeaconRequestHistoryItem,
  BeaconRequestHistoryResponse,
} from '../../types/beacon'

const CRAWLER_MODES: Array<{
  key: BeaconCrawlerMode
  label: string
  detail: string
}> = [
  { key: 'scrape', label: 'Scrape', detail: 'one URL' },
  { key: 'batch', label: 'Batch', detail: 'up to 5 URLs' },
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
  const [batchUrls, setBatchUrls] = useState('https://example.com/')
  const [query, setQuery] = useState('example domain')
  const [schemaText, setSchemaText] = useState('title: page title\nsummary: concise summary')
  const [maxPages, setMaxPages] = useState(2)
  const [maxDepth, setMaxDepth] = useState(1)
  const [approvalQueueId, setApprovalQueueId] = useState('')
  const [approval, setApproval] = useState<BeaconBrowserApprovalResponse | null>(null)
  const [result, setResult] = useState<BeaconCrawlerResult | null>(null)
  const [historyRows, setHistoryRows] = useState<BeaconRequestHistoryItem[]>([])
  const [historyQuery, setHistoryQuery] = useState('alpha_ui.beacon_crawler')
  const [historyStatus, setHistoryStatus] = useState('all')
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [exportingRequestId, setExportingRequestId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const selectedMode = useMemo(
    () => CRAWLER_MODES.find((item) => item.key === mode) ?? CRAWLER_MODES[0],
    [mode],
  )
  const parsedUrl = useMemo(() => parseCrawlerUrl(url), [url])
  const parsedBatchUrls = useMemo(() => parseBatchUrls(batchUrls), [batchUrls])
  const schema = useMemo(() => parseSchema(schemaText), [schemaText])
  const schemaFieldCount = Object.keys(schema).length
  const canRun = mode === 'batch'
    ? Boolean(parsedBatchUrls.urls.length > 0 && parsedBatchUrls.valid && !loading)
    : Boolean(url.trim() && parsedUrl.valid && !loading)
  const renderReadyToRun = mode === 'render' && Boolean(approvalQueueId.trim())

  const fetchCrawlerHistory = useCallback(async () => {
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const params = new URLSearchParams({
        limit: '6',
        q: historyQuery.trim() || 'alpha_ui.beacon_crawler',
      })
      if (historyStatus !== 'all') params.set('status', historyStatus)
      const payload = await apiJson<BeaconRequestHistoryResponse>(`/v1/internet-scout/requests?${params.toString()}`)
      setHistoryRows(payload.history ?? [])
      setHistoryLoaded(true)
    } catch (caught) {
      setHistoryRows([])
      setHistoryError(caught instanceof Error ? caught.message : 'Crawler history unavailable')
    } finally {
      setHistoryLoading(false)
    }
  }, [historyQuery, historyStatus])

  const exportCrawlerEvidence = async (requestId: string) => {
    setExportingRequestId(requestId)
    setHistoryError('')
    try {
      const payload = await apiJson<unknown>(`/v1/internet-scout/requests/${requestId}`)
      downloadJson(`beacon-crawler-evidence-${requestId.slice(0, 8)}.json`, payload)
    } catch (caught) {
      setHistoryError(caught instanceof Error ? caught.message : 'Crawler evidence export failed')
    } finally {
      setExportingRequestId('')
    }
  }

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
        batchUrls: parsedBatchUrls.urls,
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
          <h2 className="mt-1 text-lg font-semibold">Scrape, batch, map, crawl, extract, render</h2>
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
          <div className="grid gap-2 sm:grid-cols-6">
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
            {mode === 'batch' ? (
              <label className="min-w-0">
                <textarea
                  value={batchUrls}
                  onChange={(event) => setBatchUrls(event.target.value)}
                  placeholder="One URL per line, up to 5"
                  rows={3}
                  className={`min-h-11 w-full resize-y rounded-lg border bg-transparent px-3 py-2 text-sm outline-none ${border}`}
                />
              </label>
            ) : (
              <label className="relative min-w-0">
                <Globe2 className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 opacity-45" />
                <input
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder="https://example.com/"
                  className={`min-h-11 w-full rounded-lg border bg-transparent py-2 pl-10 pr-3 text-sm outline-none ${border}`}
                />
              </label>
            )}
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

          {mode === 'batch' && parsedBatchUrls.overflow && (
            <p className="text-xs text-rose-500">Batch scrape is capped at 5 URLs.</p>
          )}
          {mode === 'batch' && !parsedBatchUrls.valid && !parsedBatchUrls.overflow && (
            <p className="text-xs text-rose-500">Every batch line must be a full http or https URL.</p>
          )}
          {mode !== 'batch' && !parsedUrl.valid && <p className="text-xs text-rose-500">Enter a full http or https URL.</p>}
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

        <div className="space-y-3">
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
          <CrawlerHistoryExport
            border={border}
            softPanel={softPanel}
            isDark={isDark}
            rows={historyRows}
            query={historyQuery}
            status={historyStatus}
            loaded={historyLoaded}
            loading={historyLoading}
            error={historyError}
            exportingRequestId={exportingRequestId}
            onQueryChange={setHistoryQuery}
            onStatusChange={setHistoryStatus}
            onRefresh={fetchCrawlerHistory}
            onExport={exportCrawlerEvidence}
          />
        </div>
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
    batchUrls: string[]
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
  if (mode === 'batch') {
    return await apiJson<BeaconCrawlerBatchScrapeResponse>('/v1/internet-scout/crawler/batch-scrape', {
      method: 'POST',
      body: JSON.stringify({
        urls: options.batchUrls,
        ...(options.query.trim() ? { query: options.query.trim() } : {}),
        max_bytes: 200_000,
      }),
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
  const batch = isBatchResult(result)
  const host = batch ? `${result.succeeded_count}/${result.result_count} succeeded` : 'host' in result ? result.host : result.seed_host
  const title = batch ? 'Batch scrape complete' : 'title' in result ? result.title : null
  const canonicalUrl = batch ? '' : 'canonical_url' in result ? result.canonical_url : result.seed_url
  const cacheLabel = batch ? 'cache first' : 'cache_hit' in result ? result.cache_hit ? 'cache hit' : 'cache miss' : 'map cache n/a'
  const countLabel = resultCountLabel(result)

  return (
    <div className={`mt-4 rounded-lg border p-3 ${border} ${softPanel}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Result summary</p>
          <p className="mt-1 truncate text-sm font-semibold">{title || host}</p>
          {canonicalUrl && (
            <a
              href={canonicalUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex max-w-full items-center gap-1 truncate text-xs opacity-65 hover:opacity-100"
            >
              <ExternalLink className="h-3 w-3 shrink-0" />
              <span className="truncate">{canonicalUrl}</span>
            </a>
          )}
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
        <ResultMetric label={batch ? 'Batch' : 'Request'} value={(batch ? result.batch_id : result.request_id).slice(0, 8)} />
        <ResultMetric label="Host" value={host} />
        <ResultMetric label="Fetched" value={batch ? `${result.blocked_count} blocked` : 'fetched_at' in result ? formatCrawlerDate(result.fetched_at) : `${result.page_count} pages`} />
        <ResultMetric label="Trust boundary" value={result.raw_web_content_is_untrusted ? 'untrusted web content' : 'trusted'} />
      </div>

      <div className="mt-3 grid gap-2 lg:grid-cols-2">
        {batch && (
          <details className={`rounded-lg border p-3 ${border}`}>
            <summary className="cursor-pointer text-sm font-semibold">Batch URLs and evidence</summary>
            <BatchScrapeSummary result={result} border={border} />
          </details>
        )}

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
            <MapCrawlSummary result={result} border={border} />
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
            <GroupedLinkList links={result.links} border={border} />
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
              <div
                className={`rounded border px-2 py-1 font-mono text-[10px] uppercase ${renderQualityTone(result.render_quality_status, isDark)}`}
              >
                Render quality {result.render_quality_status}
              </div>
              <ResultMetric label="Visible text" value={`${result.visible_text_length} chars`} />
              <ResultMetric label="Approval" value={result.approval_queue_id.slice(0, 8)} />
              <ResultMetric label="Screenshot" value={result.screenshot_ref || 'not returned'} />
              <ResultMetric label="Screenshot policy" value={result.screenshot_required ? 'required' : 'optional'} />
              <ResultMetric label="Evidence sources" value={String(result.evidence_source_count)} />
              <ResultMetric label="Evidence path" value={result.evidence_path} />
              <ResultMetric label="Audit path" value={result.audit_path} />
              <ResultMetric label="Audit rows" value={String(result.action_audit_count)} />
              <ResultMetric
                label="Quality reasons"
                value={result.render_quality_reasons.length ? result.render_quality_reasons.join(', ') : 'none'}
              />
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

function MapCrawlSummary({ result, border }: { result: BeaconCrawlerMapResponse; border: string }) {
  const stopReasons = mapStopReasons(result)
  const markers = mapRiskMarkers(result)

  return (
    <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
      <div className={`rounded border p-2 ${border}`}>
        <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Why stopped</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {stopReasons.map((reason) => (
            <span key={reason} className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
              {reason}
            </span>
          ))}
        </div>
      </div>
      <div className={`rounded border p-2 ${border}`}>
        <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Blocked / robots markers</p>
        {markers.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {markers.map((marker) => (
              <span key={marker} className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px] font-mono uppercase text-amber-500 ${border}`}>
                <AlertTriangle className="h-3 w-3" />
                {marker}
              </span>
            ))}
          </div>
        ) : (
          <p className="mt-2 opacity-60">No blocked or robots markers reported.</p>
        )}
      </div>
      <p className="sm:col-span-2 opacity-60">
        Same-host crawl capped at {result.max_pages} pages and depth {result.max_depth}; forms and credential entry stay blocked.
      </p>
    </div>
  )
}

function BatchScrapeSummary({ result, border }: { result: BeaconCrawlerBatchScrapeResponse; border: string }) {
  return (
    <div className="mt-3 space-y-2 text-xs">
      <div className="grid gap-2 sm:grid-cols-4">
        <ResultMetric label="Succeeded" value={String(result.succeeded_count)} />
        <ResultMetric label="Blocked" value={String(result.blocked_count)} />
        <ResultMetric label="Failed" value={String(result.failed_count)} />
        <ResultMetric label="Cap" value={`${result.max_urls} URLs`} />
      </div>
      <p className="opacity-60">
        Batch scrape is cache-first, non-rendered, and capped to public read-only URLs.
      </p>
      {result.items.map((item, index) => (
        <div key={`${item.url}-${index}`} className={`rounded border p-2 ${border}`}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate font-semibold">{item.title || item.host || item.url}</p>
              <a
                href={item.canonical_url || item.url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-flex max-w-full items-center gap-1 truncate opacity-65 hover:opacity-100"
              >
                <ExternalLink className="h-3 w-3 shrink-0" />
                <span className="truncate">{item.canonical_url || item.url}</span>
              </a>
            </div>
            <span className={`rounded border px-2 py-1 text-[10px] font-mono uppercase ${border}`}>
              {item.status}
            </span>
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            <ResultMetric label="Request" value={item.request_id ? item.request_id.slice(0, 8) : 'none'} />
            <ResultMetric label="Cache" value={item.cache_hit == null ? 'cache n/a' : item.cache_hit ? 'cache hit' : 'cache miss'} />
            <ResultMetric label="Issue" value={item.blocked_reasons.join(', ') || item.error_type || 'none'} />
          </div>
          {item.text && <p className="mt-2 line-clamp-3 whitespace-pre-wrap opacity-65">{item.text}</p>}
        </div>
      ))}
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

function GroupedLinkList({ links, border }: { links: string[]; border: string }) {
  const groups = groupLinksByHost(links)
  if (groups.length === 0) return null
  return (
    <div className="mt-3 space-y-2">
      <p className="text-[10px] font-mono uppercase tracking-widest opacity-45">Link groups by host</p>
      {groups.slice(0, 6).map((group) => (
        <details key={group.host} className={`rounded border p-2 text-xs ${border}`}>
          <summary className="cursor-pointer font-semibold">
            {group.host} · {group.links.length} links
          </summary>
          <LinkList links={group.links} border={border} />
        </details>
      ))}
    </div>
  )
}

function CrawlerHistoryExport({
  border,
  softPanel,
  isDark,
  rows,
  query,
  status,
  loaded,
  loading,
  error,
  exportingRequestId,
  onQueryChange,
  onStatusChange,
  onRefresh,
  onExport,
}: {
  border: string
  softPanel: string
  isDark: boolean
  rows: BeaconRequestHistoryItem[]
  query: string
  status: string
  loaded: boolean
  loading: boolean
  error: string
  exportingRequestId: string
  onQueryChange: (value: string) => void
  onStatusChange: (value: string) => void
  onRefresh: () => void
  onExport: (requestId: string) => void
}) {
  return (
    <details
      className={`rounded-lg border p-3 text-xs ${border} ${softPanel}`}
      onToggle={(event) => {
        if (event.currentTarget.open && !loaded && !loading) onRefresh()
      }}
    >
      <summary className="cursor-pointer font-semibold">Crawler history and export</summary>
      <div className="mt-3 grid gap-2">
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search crawler request, host, status"
          className={`min-h-10 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
        />
        <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
          <select
            value={status}
            onChange={(event) => onStatusChange(event.target.value)}
            className={`min-h-10 rounded-lg border bg-transparent px-3 text-sm outline-none ${border}`}
          >
            <option value="all">All status</option>
            <option value="succeeded">Succeeded</option>
            <option value="running">Running</option>
            <option value="failed">Failed</option>
            <option value="blocked">Blocked</option>
          </select>
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border px-3 text-sm disabled:opacity-45 ${border}`}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
        {error && <p className="text-sm text-rose-500">{error}</p>}
        {loading && <p className="text-sm opacity-55">Loading crawler history.</p>}
        {!loading && loaded && rows.length === 0 && (
          <p className="text-sm opacity-55">No crawler runs match this view.</p>
        )}
        {!loading && rows.map((item) => (
          <CrawlerHistoryRow
            key={item.request_id}
            item={item}
            border={border}
            isDark={isDark}
            exporting={exportingRequestId === item.request_id}
            onExport={onExport}
          />
        ))}
      </div>
    </details>
  )
}

function CrawlerHistoryRow({
  item,
  border,
  isDark,
  exporting,
  onExport,
}: {
  item: BeaconRequestHistoryItem
  border: string
  isDark: boolean
  exporting: boolean
  onExport: (requestId: string) => void
}) {
  const operation = item.crawler_operation || item.latest_event_type?.replaceAll('_', ' ') || 'crawler'
  const cache = item.crawler_cache_hit == null ? 'cache n/a' : item.crawler_cache_hit ? 'cache hit' : 'cache miss'
  const blocked = item.crawler_blocked_reasons?.join(', ') || item.crawler_error_type || 'no block'

  return (
    <div className={`rounded border p-2 ${border} ${isDark ? 'bg-black/15' : 'bg-white/35'}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-semibold">{operation} · {item.status}</p>
          <p className="mt-0.5 font-mono text-[10px] uppercase opacity-50">
            {item.request_id.slice(0, 8)} · {formatCrawlerDate(item.created_at)}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onExport(item.request_id)}
          disabled={exporting}
          className={`inline-flex min-h-9 items-center gap-2 rounded border px-2 text-[10px] font-mono uppercase disabled:opacity-45 ${border}`}
        >
          {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          Export evidence
        </button>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        <ResultMetric label="Cache" value={cache} />
        <ResultMetric label="Pages / links" value={`${item.crawler_page_count ?? 0}p · ${item.crawler_link_count ?? 0} links`} />
        <ResultMetric label="Blocked" value={blocked} />
      </div>
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

function parseBatchUrls(value: string): { urls: string[]; valid: boolean; overflow: boolean } {
  const urls = Array.from(new Set(value.split(/\s+/).map((item) => item.trim()).filter(Boolean)))
  const overflow = urls.length > 5
  return {
    urls: urls.slice(0, 5),
    valid: !overflow && urls.every((item) => parseCrawlerUrl(item).valid),
    overflow,
  }
}

function clampNumber(value: string, min: number, max: number): number {
  const parsed = Number.parseInt(value, 10)
  if (Number.isNaN(parsed)) return min
  return Math.min(max, Math.max(min, parsed))
}

function modeIcon(mode: BeaconCrawlerMode) {
  if (mode === 'batch') return <FileSearch className="h-4 w-4" />
  if (mode === 'map' || mode === 'crawl') return <Network className="h-4 w-4" />
  if (mode === 'extract') return <FileSearch className="h-4 w-4" />
  if (mode === 'render') return <Camera className="h-4 w-4" />
  return <Search className="h-4 w-4" />
}

function resultCountLabel(result: BeaconCrawlerResult): string {
  if ('items' in result) return `${result.result_count} URLs`
  if ('fields' in result) return `${result.fields.length} fields`
  if ('page_count' in result) return `${result.page_count} pages · ${result.link_count} links`
  return `${result.links.length} links`
}

function isBatchResult(result: BeaconCrawlerResult): result is BeaconCrawlerBatchScrapeResponse {
  return 'items' in result
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

function renderQualityTone(status: BeaconCrawlerRenderResponse['render_quality_status'], isDark: boolean) {
  if (status === 'ok') {
    return isDark
      ? 'border-emerald-300/30 bg-emerald-300/10 text-emerald-100'
      : 'border-emerald-500/25 bg-emerald-500/10 text-emerald-800'
  }
  if (status === 'empty') {
    return isDark
      ? 'border-rose-300/30 bg-rose-300/10 text-rose-100'
      : 'border-rose-500/25 bg-rose-500/10 text-rose-800'
  }
  return isDark
    ? 'border-amber-300/30 bg-amber-300/10 text-amber-100'
    : 'border-amber-500/25 bg-amber-500/10 text-amber-800'
}

function groupLinksByHost(links: string[]): Array<{ host: string; links: string[] }> {
  const groups = new Map<string, string[]>()
  for (const link of links) {
    const host = linkHost(link)
    groups.set(host, [...(groups.get(host) ?? []), link])
  }
  return [...groups.entries()].map(([host, groupLinks]) => ({ host, links: groupLinks }))
}

function linkHost(link: string): string {
  try {
    return new URL(link).host.toLowerCase()
  } catch {
    return 'unparsed'
  }
}

function mapStopReasons(result: BeaconCrawlerMapResponse): string[] {
  const reasons: string[] = []
  const deepest = Math.max(0, ...result.pages.map((page) => page.depth))
  if (result.page_count >= result.max_pages) reasons.push(`page cap ${result.max_pages}`)
  if (deepest >= result.max_depth) reasons.push(`depth cap d${result.max_depth}`)
  if (result.links.length === 0) reasons.push('no same-host links')
  if (result.page_count === 0) reasons.push('no pages fetched')
  return reasons.length > 0 ? reasons : ['completed within caps']
}

function mapRiskMarkers(result: BeaconCrawlerMapResponse): string[] {
  return [
    ...new Set(
      result.pages.flatMap((page) => [
        ...page.risk_markers,
        ...(page.truncated ? ['page_truncated'] : []),
      ]),
    ),
  ].slice(0, 8)
}

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
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
