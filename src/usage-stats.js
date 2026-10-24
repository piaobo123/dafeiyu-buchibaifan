/**
 * Token-usage folding for the desktop pet's CNY cost strip.
 *
 * The DSH host exposes `sessionQuery.listSessions()` / `readSession(id)`, and
 * every session log carries the same four usage buckets the official
 * `dsh-token-pet` plugin reads. This module folds those logs into
 * `(provider, model, local-day)` cells and prices each usage event with
 * DeepSeek's published peak / off-peak CNY rates.
 *
 * DeepSeek peak hours (Beijing time, Mon-Fri, excluding public holidays):
 * 09:00-12:00 and 14:00-18:00. Every other hour is billed at half price.
 * Public holidays are not known offline; only the weekday rule is applied.
 * The balance shown beside these numbers comes from
 * `deepseekAccount.getBalance()` and is exact.
 */

export const ZERO_TOKENS = Object.freeze({
  uncachedInputTokens: 0,
  outputTokens: 0,
  cacheReadTokens: 0,
  cacheWriteTokens: 0,
})

const FLASH_PRICE = Object.freeze({
  peak: { input: 2, output: 8, cacheRead: 0.04, cacheWrite: 2 },
  offPeak: { input: 1, output: 4, cacheRead: 0.02, cacheWrite: 1 },
})

const PRO_PRICE = Object.freeze({
  peak: { input: 9, output: 27, cacheRead: 0.3, cacheWrite: 9 },
  offPeak: { input: 4.5, output: 13.5, cacheRead: 0.15, cacheWrite: 4.5 },
})

/** CNY per 1M tokens, split by DeepSeek peak / off-peak billing. */
export const PRICE_CNY = Object.freeze({
  'deepseek-flash': FLASH_PRICE,
  'deepseek-chat': FLASH_PRICE,
  'deepseek-v4-flash': FLASH_PRICE,
  'deepseek-v4.1-flash': FLASH_PRICE,
  'deepseek-v4-pro': PRO_PRICE,
  'deepseek-reasoner': PRO_PRICE,
  '*': FLASH_PRICE,
})

const positive = (value) =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0

export function addTokens(left, right) {
  return {
    uncachedInputTokens: left.uncachedInputTokens + right.uncachedInputTokens,
    outputTokens: left.outputTokens + right.outputTokens,
    cacheReadTokens: left.cacheReadTokens + right.cacheReadTokens,
    cacheWriteTokens: left.cacheWriteTokens + right.cacheWriteTokens,
  }
}

export function totalTokens(tokens) {
  return (
    tokens.uncachedInputTokens +
    tokens.outputTokens +
    tokens.cacheReadTokens +
    tokens.cacheWriteTokens
  )
}

export function normalizeTokens(usage) {
  return {
    uncachedInputTokens: positive(usage?.inputTokens),
    outputTokens: positive(usage?.outputTokens),
    cacheReadTokens: positive(usage?.cacheReadTokens),
    cacheWriteTokens: positive(usage?.cacheWriteTokens),
  }
}

/** The event shapes that carry billable usage (mirrors the official plugin). */
export function usageOf(event) {
  const data = event?.data
  if (event?.type === 'assistant/chunk') {
    const chunk = data?.chunk
    return chunk?.type === 'usage' && chunk.usage && typeof chunk.usage === 'object'
      ? chunk.usage
      : undefined
  }
  if (event?.type === 'assistant/message' || event?.type === 'step/end' || event?.type === 'turn/end') {
    const usage = data?.usage ?? data?.step?.usage ?? data?.turn?.usage
    return usage && typeof usage === 'object' ? usage : undefined
  }
  return undefined
}

/** The routed model is announced by request/header and inherited downwards. */
export function modelOf(event) {
  if (event?.type !== 'request/header') return undefined
  const header = event.data?.header
  const provider =
    (typeof header?.config?.provider === 'string' && header.config.provider) ||
    (typeof header?.provider === 'string' && header.provider) ||
    undefined
  const model =
    (typeof header?.config?.model === 'string' && header.config.model) ||
    (typeof header?.model === 'string' && header.model) ||
    undefined
  return provider && model ? { provider, model } : undefined
}

const identityPart = (value) => {
  if (typeof value === 'string' && value !== '') return value
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (value && typeof value === 'object') {
    const id = value.id
    if (typeof id === 'string' && id !== '') return id
    if (typeof id === 'number' && Number.isFinite(id)) return id
  }
  return undefined
}

function eventIdentity(event) {
  const data = event?.data
  const turn = identityPart(data?.turnId) ?? identityPart(data?.turn)
  const step = identityPart(data?.stepId) ?? identityPart(data?.step)
  return turn !== undefined && step !== undefined ? `${turn}\u0000${step}` : undefined
}

const isTerminal = (type) =>
  type === 'turn/end' || type === 'step/end' || type === 'assistant/message'

export function localDay(ms) {
  const date = new Date(ms)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** Beijing time is a fixed UTC+8 offset (no DST), so this is safe offline. */
export function isPeakBeijing(ms) {
  const beijing = new Date(ms + 8 * 60 * 60 * 1000)
  const weekday = beijing.getUTCDay()
  if (weekday === 0 || weekday === 6) return false
  const hour = beijing.getUTCHours()
  return (hour >= 9 && hour < 12) || (hour >= 14 && hour < 18)
}

function epochMs(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return undefined
  if (value < 1e11) return value * 1000
  if (value > 1e14) return value / 1000
  return value
}

/**
 * Fold one session's events into `(provider, model, day)` cells.
 * Streaming usage chunks are deduplicated per (turn, step); a terminal event
 * overrides the partial chunk for the same step. Each event is priced with the
 * peak / off-peak rate that applied at its own timestamp.
 */
export function foldUsageEvents(events, fallbackDay, now = Date.now()) {
  const cells = new Map()
  let currentModel
  const selected = new Map()
  const retained = new Set()

  for (const [index, event] of (events ?? []).entries()) {
    const model = modelOf(event)
    if (model) currentModel = model
    const usage = usageOf(event)
    if (!usage) {
      retained.add(index)
      continue
    }
    const key = eventIdentity(event)
    if (!key) {
      retained.add(index)
      continue
    }
    const previous = selected.get(key)
    const terminal = isTerminal(event.type)
    if (!previous || terminal || !previous.terminal) {
      if (previous) retained.delete(previous.index)
      selected.set(key, { index, terminal })
      retained.add(index)
    }
  }

  for (const [index, event] of (events ?? []).entries()) {
    if (!retained.has(index)) continue
    const model = modelOf(event)
    if (model) currentModel = model
    const usage = usageOf(event)
    if (!usage) continue
    const tokens = normalizeTokens(usage)
    if (totalTokens(tokens) === 0) continue
    const stamp = epochMs(event.time) ?? now
    const day = stamp === fallbackDay && fallbackDay ? fallbackDay : localDay(stamp)
    const owner = currentModel ?? { provider: '(unknown)', model: '(unknown)' }
    const id = `${owner.provider}\u0000${owner.model}\u0000${day}`
    const cell = cells.get(id) ?? {
      provider: owner.provider,
      model: owner.model,
      day,
      totals: { ...ZERO_TOKENS },
      cny: 0,
      peakCny: 0,
      offPeakCny: 0,
    }
    cell.totals = addTokens(cell.totals, tokens)
    const peak = isPeakBeijing(stamp)
    const price = resolvePrice(owner.model)
    const cost = costOfTokens(tokens, peak ? price.peak : price.offPeak)
    cell.cny += cost
    if (peak) cell.peakCny += cost
    else cell.offPeakCny += cost
    cells.set(id, cell)
  }

  for (const cell of cells.values()) cell.total = totalTokens(cell.totals)
  return cells
}

export function resolvePrice(model, table = PRICE_CNY) {
  const name = String(model ?? '')
  if (table[name]) return table[name]
  const prefixes = Object.keys(table)
    .filter((key) => key.endsWith('*') && key.length > 1)
    .sort((left, right) => right.length - left.length)
  for (const key of prefixes) {
    if (name.startsWith(key.slice(0, -1))) return table[key]
  }
  return table['*']
}

/** CNY cost of one token bucket at a single price row. */
export function costOfTokens(tokens, price) {
  return (
    (positive(tokens.uncachedInputTokens) / 1e6) * price.input +
    (positive(tokens.outputTokens) / 1e6) * price.output +
    (positive(tokens.cacheReadTokens) / 1e6) * price.cacheRead +
    (positive(tokens.cacheWriteTokens) / 1e6) * price.cacheWrite
  )
}

export function mergeCells(target, source) {
  for (const cell of source.values()) {
    const id = `${cell.provider}\u0000${cell.model}\u0000${cell.day}`
    const existing = target.get(id)
    if (existing) {
      existing.totals = addTokens(existing.totals, cell.totals)
      existing.cny += cell.cny ?? 0
      existing.peakCny += cell.peakCny ?? 0
      existing.offPeakCny += cell.offPeakCny ?? 0
    } else {
      target.set(id, {
        ...cell,
        totals: { ...cell.totals },
        cny: cell.cny ?? 0,
        peakCny: cell.peakCny ?? 0,
        offPeakCny: cell.offPeakCny ?? 0,
      })
    }
  }
  for (const cell of target.values()) cell.total = totalTokens(cell.totals)
  return target
}

export function summarize(cells, now = Date.now()) {
  const day = localDay(now)
  const month = day.slice(0, 7)
  let todayCny = 0
  let monthCny = 0
  let todayTokens = { ...ZERO_TOKENS }
  let monthTokens = { ...ZERO_TOKENS }
  const byModel = new Map()

  for (const cell of cells.values()) {
    if (cell.day === day) {
      todayCny += cell.cny ?? 0
      todayTokens = addTokens(todayTokens, cell.totals)
    }
    if (cell.day.startsWith(month)) {
      monthCny += cell.cny ?? 0
      monthTokens = addTokens(monthTokens, cell.totals)
      const key = `${cell.provider}\u0000${cell.model}`
      const row = byModel.get(key) ?? {
        provider: cell.provider,
        model: cell.model,
        cny: 0,
        tokens: { ...ZERO_TOKENS },
      }
      row.cny += cell.cny ?? 0
      row.tokens = addTokens(row.tokens, cell.totals)
      byModel.set(key, row)
    }
  }

  return {
    day,
    month,
    todayCny,
    monthCny,
    todayTokens,
    monthTokens,
    todayTotal: totalTokens(todayTokens),
    monthTotal: totalTokens(monthTokens),
    byModel: [...byModel.values()].sort((left, right) => right.cny - left.cny),
  }
}

/**
 * Enumerate every session and fold its usage. Closed sessions are cached by
 * header fingerprint so a refresh only re-reads live or changed logs.
 */
export async function collectUsage(sessionQuery, cache, now = Date.now()) {
  if (!sessionQuery?.listSessions || !sessionQuery?.readSession) return undefined
  const records = await sessionQuery.listSessions()
  const cells = new Map()
  for (const record of records ?? []) {
    const id = record?.header?.id
    if (!id) continue
    const fingerprint = fingerprintOf(record)
    const cached = cache.get(id)
    if (!record.live && cached && cached.fingerprint === fingerprint) {
      mergeCells(cells, cached.cells)
      continue
    }
    let source
    try {
      source = await sessionQuery.readSession(id)
    } catch {
      if (cached) mergeCells(cells, cached.cells)
      continue
    }
    const createdAt = typeof source?.session?.createdAt === 'number' ? source.session.createdAt : 0
    const folded = foldUsageEvents(source?.events ?? [], createdAt ? localDay(createdAt) : undefined, now)
    if (!record.live) cache.set(id, { fingerprint, cells: folded })
    mergeCells(cells, folded)
  }
  return summarize(cells, now)
}

export function fingerprintOf(record) {
  const header = record?.header ?? {}
  const parts = []
  if (header.revision !== undefined) parts.push(String(header.revision))
  if (header.updatedAt !== undefined) parts.push(String(header.updatedAt))
  if (header.eventCount !== undefined) parts.push(String(header.eventCount))
  if (parts.length === 0) parts.push(JSON.stringify([header.version, header.id, header.createdAt, header.cwd]))
  return (record?.live ? 'live:' : 'closed:') + parts.join('|')
}

export function formatCny(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  if (Math.abs(value) >= 100) return value.toFixed(1)
  return value.toFixed(2)
}

/** Progress-bar denominator: decade tiers 1000 -> 10000 -> 100000, min 1,000. */
export function balanceBarMax(capCny) {
  const cap = typeof capCny === 'number' && Number.isFinite(capCny) && capCny > 0 ? capCny : 1000
  let max = 1000
  while (cap > max) max *= 10
  return max
}