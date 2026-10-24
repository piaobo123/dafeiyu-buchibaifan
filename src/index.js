import Schema from '@deepseek-ai/schemastery'
import { mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { CompanionReducer } from './companion-reducer.js'
import { HelperProcess } from './helper-process.js'
import {
  CompanionMessageKind,
  CompanionState,
  createMessage,
} from './protocol.js'
import { balanceBarMax, collectUsage, formatCny } from './usage-stats.js'

/** A writable scratch dir for the one-file helper (its bootloader extracts here). */
export function helperTempDir() {
  const home = process.env.DSH_HOME?.trim()
  return join(home ? home : join(homedir(), '.dsh'), 'dsh-dafeiyu', 'runtime')
}

export const name = 'dafeiyu-buchibaifan'
export const inject = ['sessions']
export const CONFIG_ENDPOINT = '/plugins/dafeiyu-buchibaifan/config'
export const STATS_ENDPOINT = '/plugins/dafeiyu-buchibaifan/stats'
export const Config = Schema.object({
  enabled: Schema.boolean().default(true).description('启用桌面大肥鱼'),
  scale: Schema.number().min(0.5).max(1.4).step(0.05).default(1).role('slider').description('角色大小'),
  bubbleScale: Schema.number().min(0.8).max(1.2).step(0.05).default(1).role('slider').description('气泡大小'),
  activityLevel: Schema.union([
    Schema.const('quiet').description('安静'),
    Schema.const('normal').description('标准'),
    Schema.const('lively').description('活泼'),
  ]).default('normal').description('空闲微动作频率'),
  reducedMotion: Schema.boolean().default(false).description('减少走动、循环帧和程序化晃动'),
  includeSubagents: Schema.boolean().default(false).description('允许子 Agent 抢占宠物状态'),
  useSeparateCard: Schema.boolean().default(true).role('switch').description('状态/余额卡片用独立悬浮窗口（始终在屏幕内；关闭则用回旧的窗口内手绘卡片）'),
  showStats: Schema.boolean().default(true).role('switch').description('在桌宠下方常驻显示今日消耗 / 本月消耗 / 余额'),
  balanceCapCny: Schema.number().min(100).max(20000).step(100).default(1000).role('slider').description('余额进度条基准额度（元）；进度条按整千向上取整，最低 1000'),
  actionCooldownMs: Schema.number().min(200).max(4000).step(50).default(800).role('slider').description('两次动作切换之间的最小间隔（毫秒）'),
  actionDwellMs: Schema.number().min(400).max(6000).step(100).default(1500).role('slider').description('每个动作至少停留多久才允许切换（毫秒）'),
}).description('由 DeepSeek Harness 状态驱动的桌面大肥鱼伴侣')

const defaults = Object.freeze({
  enabled: true,
  scale: 1,
  bubbleScale: 1,
  activityLevel: 'normal',
  reducedMotion: false,
  includeSubagents: false,
  useSeparateCard: true,
  showStats: true,
  balanceCapCny: 1000,
  actionCooldownMs: 800,
  actionDwellMs: 1500,
})

function normalizeCapCny(value) {
  const numeric = typeof value === 'number' && Number.isFinite(value) ? value : defaults.balanceCapCny
  return Math.max(100, Math.min(20000, numeric))
}

function publicConfig(config = {}) {
  return {
    enabled: config.enabled ?? defaults.enabled,
    scale: config.scale ?? defaults.scale,
    bubbleScale: config.bubbleScale ?? defaults.bubbleScale,
    activityLevel: config.activityLevel ?? defaults.activityLevel,
    reducedMotion: config.reducedMotion ?? defaults.reducedMotion,
    includeSubagents: config.includeSubagents ?? defaults.includeSubagents,
    useSeparateCard: config.useSeparateCard ?? defaults.useSeparateCard,
    showStats: config.showStats ?? defaults.showStats,
    balanceCapCny: normalizeCapCny(config.balanceCapCny),
    actionCooldownMs: config.actionCooldownMs ?? defaults.actionCooldownMs,
    actionDwellMs: config.actionDwellMs ?? defaults.actionDwellMs,
  }
}

function localSettingsScope(value) {
  return {
    get: () => value,
    watch: () => () => {},
  }
}

function jsonResponse(res, status, body) {
  const payload = JSON.stringify(body)
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'content-length': Buffer.byteLength(payload),
  })
  res.end(payload)
}

function isLoopback(address) {
  return address === '127.0.0.1' || address === '::1' || address === '::ffff:127.0.0.1'
}

async function readPatch(req) {
  const chunks = []
  let bytes = 0
  for await (const chunk of req) {
    bytes += chunk.length
    if (bytes > 8192) throw new Error('request body is too large')
    chunks.push(chunk)
  }
  const value = JSON.parse(Buffer.concat(chunks).toString('utf8'))
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('patch must be an object')
  const allowed = new Set(Object.keys(defaults))
  if (Object.keys(value).some((key) => !allowed.has(key))) throw new Error('patch contains an unknown setting')
  return value
}

export function createConfigHandler(settings) {
  return async (req, res) => {
    if (!isLoopback(req.socket?.remoteAddress)) {
      jsonResponse(res, 403, { error: 'local access only' })
      return
    }
    const origin = req.headers?.origin
    if (origin) {
      let originHost
      try { originHost = new URL(origin).host } catch {}
      if (!originHost || originHost !== req.headers.host) {
        jsonResponse(res, 403, { error: 'origin mismatch' })
        return
      }
    }
    if (req.method === 'GET') {
      jsonResponse(res, 200, settings.get())
      return
    }
    if (req.method !== 'PATCH') {
      jsonResponse(res, 405, { error: 'method not allowed' })
      return
    }
    try {
      await settings.update(await readPatch(req))
      jsonResponse(res, 200, settings.get())
    } catch (error) {
      jsonResponse(res, 400, { error: error instanceof Error ? error.message : String(error) })
    }
  }
}

function mount(ctx, config = {}, eventCtx = ctx) {
  const logger = ctx.logger ?? console
  const base = publicConfig(config)
  const settings = ctx.settings?.register?.('dafeiyu-buchibaifan', Config, {
    base,
    applies: 'live',
  }) ?? localSettingsScope(base)

  let bridge
  let reducer
  let restartTimer

  const stopRuntime = (reason = 'settings-change') => {
    bridge?.stop(reason)
    bridge = undefined
    reducer = undefined
  }

  const restartRuntime = (next) => {
    stopRuntime('settings-change')
    void startRuntime(next)
  }

  // The credentials service is mounted by the base bundle after this plugin
  // (which injects on 'settings') starts, so the first resolveApiKey() can
  // legitimately come up empty on a fresh host boot. Retry briefly: as soon
  // as the key resolves, respawn the helper so the balance lookup self-heals
  // without a manual disable/enable.
  let apiKeyRetryTimer
  const scheduleApiKeyRetry = () => {
    if (apiKeyRetryTimer) return
    let attempt = 0
    const tryResolve = async () => {
      attempt += 1
      let key
      try { key = await resolveApiKey() } catch { key = undefined }
      if (key !== undefined) {
        apiKeyRetryTimer = undefined
        logger.info?.('dsh-dafeiyu: DeepSeek API key resolved after startup; restarting helper')
        restartRuntime(settings.get())
        return
      }
      if (attempt < 6) {
        apiKeyRetryTimer = setTimeout(tryResolve, 4000)
        apiKeyRetryTimer.unref?.()
      } else {
        apiKeyRetryTimer = undefined
      }
    }
    apiKeyRetryTimer = setTimeout(tryResolve, 4000)
    apiKeyRetryTimer.unref?.()
  }

  const applyLiveSettings = (next) => {
    for (const message of reducer.setIncludeSubagents(next.includeSubagents === true)) bridge.send(message)
    bridge.send(createMessage(CompanionMessageKind.CONFIG, {
      scale: next.scale ?? defaults.scale,
      bubbleScale: next.bubbleScale ?? defaults.bubbleScale,
      activityLevel: next.activityLevel ?? defaults.activityLevel,
      reducedMotion: next.reducedMotion === true,
      useSeparateCard: next.useSeparateCard !== false,
      showStats: next.showStats !== false,
      balanceCapCny: next.balanceCapCny ?? defaults.balanceCapCny,
      actionCooldownMs: next.actionCooldownMs ?? defaults.actionCooldownMs,
      actionDwellMs: next.actionDwellMs ?? defaults.actionDwellMs,
    }))
  }

  // --- Chinese-yuan cost strip (today / month / balance) ------------------
  // Token usage is folded from the DSH session corpus; the balance comes from
  // the platform account service (exact), while the cost figures are list-price
  // estimates because DeepSeek bills peak hours at twice the off-peak rate.
  const usageCache = new Map()
  let latestStats
  let statsInFlight = false
  let statsTimer
  let statsDebounceTimer
  let lastStatsSignature = ''

  const readWalletCny = async () => {
    const account = ctx.get('deepseekAccount', false)
    if (!account?.getBalance) return undefined
    try {
      const result = await account.getBalance({
        version: '1.0.0',
        locale: 'zh-CN',
        timezoneOffsetSeconds: -new Date().getTimezoneOffset() * 60,
      })
      if (result?.status !== 'ready') return undefined
      const pick = (wallets) => {
        const list = Array.isArray(wallets) ? wallets : []
        const cny = list.find((wallet) => wallet?.currency === 'CNY')
        if (cny) return Number(cny.balance)
        const usd = list.find((wallet) => wallet?.currency === 'USD')
        if (usd) return Number(usd.balance) * 7.2
        return undefined
      }
      const balance = pick(result.value)
      const bonus = pick(result.bonusWallets)
      return {
        balanceCny: Number.isFinite(balance) ? balance : undefined,
        bonusCny: Number.isFinite(bonus) ? bonus : undefined,
      }
    } catch (error) {
      logger.warn?.(`dsh-dafeiyu balance lookup failed: ${error.message}`)
      return undefined
    }
  }

  const computeStats = async (reason) => {
    const now = Date.now()
    let usage
    try {
      const sessionQuery = ctx.get('sessionQuery', false)
      usage = await collectUsage(sessionQuery, usageCache, now)
    } catch (error) {
      logger.warn?.(`dsh-dafeiyu usage scan failed: ${error.message}`)
    }
    const wallet = await readWalletCny()
    const live = settings.get()
    return {
      todayCny: usage?.todayCny ?? null,
      monthCny: usage?.monthCny ?? null,
      balanceCny: wallet?.balanceCny ?? null,
      bonusCny: wallet?.bonusCny ?? null,
      balanceCapCny: normalizeCapCny(live.balanceCapCny),
      balanceBarMaxCny: balanceBarMax(normalizeCapCny(live.balanceCapCny)),
      day: usage?.day ?? null,
      month: usage?.month ?? null,
      todayTokens: usage?.todayTokens ?? null,
      monthTokens: usage?.monthTokens ?? null,
      todayTotal: usage?.todayTotal ?? null,
      monthTotal: usage?.monthTotal ?? null,
      byModel: usage?.byModel ?? [],
      currency: 'CNY',
      estimate: true,
      updatedAt: now,
      reason,
    }
  }

  const pushStats = async (reason = 'timer', force = false) => {
    if (statsInFlight) return
    statsInFlight = true
    try {
      const next = await computeStats(reason)
      latestStats = next
      const signature = [next.todayCny, next.monthCny, next.balanceCny]
        .map((value) => (typeof value === 'number' ? value.toFixed(4) : 'x'))
        .join('|')
      if (!force && signature === lastStatsSignature) return
      lastStatsSignature = signature
      bridge?.send(createMessage(CompanionMessageKind.STATS, {
        todayCny: next.todayCny,
        monthCny: next.monthCny,
        balanceCny: next.balanceCny,
        bonusCny: next.bonusCny,
        balanceCapCny: next.balanceCapCny,
        balanceBarMaxCny: next.balanceBarMaxCny,
        estimate: true,
        updatedAt: next.updatedAt,
      }))
    } catch (error) {
      logger.warn?.(`dsh-dafeiyu stats push failed: ${error.message}`)
    } finally {
      statsInFlight = false
    }
  }

  const scheduleStatsRefresh = (delayMs = 2000) => {
    if (statsDebounceTimer) clearTimeout(statsDebounceTimer)
    statsDebounceTimer = setTimeout(() => {
      statsDebounceTimer = undefined
      void pushStats('session')
    }, delayMs)
    statsDebounceTimer.unref?.()
  }

  const startStatsLoop = () => {
    if (statsTimer) return
    setTimeout(() => { void pushStats('start', true) }, 1500).unref?.()
    statsTimer = setInterval(() => { void pushStats('timer') }, 60_000)
    statsTimer.unref?.()
  }

  const stopStatsLoop = () => {
    if (statsTimer) clearInterval(statsTimer)
    statsTimer = undefined
    if (statsDebounceTimer) clearTimeout(statsDebounceTimer)
    statsDebounceTimer = undefined
  }

  const scheduleRestart = (next) => {
    if (restartTimer) clearTimeout(restartTimer)
    restartTimer = setTimeout(() => {
      restartTimer = undefined
      restartRuntime(next)
    }, 400)
    restartTimer.unref?.()
  }

  // Resolve the DeepSeek API key for the balance lookup: prefer the process
  // environment, then the DSH credential store (`$DSH_HOME/.credentials.yaml`,
  // the same key the chat route uses). Missing credentials degrade gracefully —
  // the helper shows a "not configured" hint instead of failing.
  const resolveApiKey = async () => {
    if (process.env.DEEPSEEK_API_KEY) return process.env.DEEPSEEK_API_KEY
    try {
      const credentials = ctx.get('credentials', false)
      if (credentials?.resolve) {
        const resolved = await credentials.resolve('DEEPSEEK_API_KEY')
        if (resolved?.value) return resolved.value
      }
    } catch {
      // Credential resolution is best-effort; absence only disables the balance card.
    }
    return undefined
  }

  // --- Desktop question answering ----------------------------------------
  // The api-proxy holds pending user-questions keyed by an rpcId it mints at
  // ask() time and pushes on the SSE mux stream (the same stream the browser
  // consumes). We subscribe to that stream to learn rpcIds, then answer via
  // POST /api/respond — the same endpoint the browser uses — so a question
  // can be answered from the desktop pet without touching the browser.
  // When the user picks "open in browser" we simply do NOT respond here: the
  // browser provider stays live and the question stays answerable there.

  /** sessionId → { rpcId, questions } from question/requested mux frames. */
  const pendingQuestionsBySession = new Map()
  let muxSocket
  let muxRetryTimer
  let muxRetryCount = 0

  const baseUrlOf = () => {
    // Prefer the DSH web URL env (set for host plugins), fall back to 3080.
    try {
      const url = new URL(process.env.DSH_WEB_URL ?? 'http://127.0.0.1:3080')
      return url.origin
    } catch {
      return 'http://127.0.0.1:3080'
    }
  }

  // DSH 0.1.2 web gates every /api request behind a signed browser-session
  // cookie (the `/api` route answers 401 without it). The plugin is a host
  // plugin, so it can reuse the connection service's launch-token exchange to
  // mint that cookie in-process instead of guessing: `authenticatedUrl()` adds
  // the launch token, and fetching it with `redirect: 'manual'` returns the
  // 303 whose Set-Cookie is the session cookie the fence will accept. The
  // cookie is cached because the user-questions provider stays live across
  // questions; a 401 clears it so the next answer re-mints a fresh one.
  let webSessionCookie
  const getWebSessionCookie = async () => {
    if (webSessionCookie !== undefined) return webSessionCookie
    try {
      const connection = ctx.get('connection', false)
      if (!connection?.authenticatedUrl) return undefined
      const response = await fetch(connection.authenticatedUrl(baseUrlOf()), { redirect: 'manual' })
      const setCookie = response.headers.get('set-cookie')
      if (!setCookie) return undefined
      // Keep only the name=value pair; the trailing attributes are for the
      // browser and would be sent back verbatim, which no Cookie parser wants.
      webSessionCookie = setCookie.split(';')[0].trim()
      return webSessionCookie
    } catch (error) {
      logger.warn?.(`dsh-dafeiyu web auth cookie fetch failed: ${error.message}`)
      return undefined
    }
  }

  const startMux = async () => {
    stopMux()
    try {
      // The harness serves /api/events.mux ONLY over a WebSocket downlink — a
      // plain HTTP GET answers 426 "upgrade required" — so the question
      // listener must open a WebSocket like the browser client does. Node
      // >=22 ships a native WebSocket client.
      const url = new URL('/api/events.mux', baseUrlOf())
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      const socket = new WebSocket(url)
      muxSocket = socket
      socket.addEventListener('open', () => {
        muxRetryCount = 0
        logger.debug?.('dsh-dafeiyu mux connected')
      })
      socket.addEventListener('message', (event) => {
        try {
          const frame = JSON.parse(String(event.data))
          if (frame?.payload?.type === 'question/requested') {
            pendingQuestionsBySession.set(String(frame.payload.sessionId), {
              rpcId: frame.rpcId,
              questions: frame.payload.questions ?? [],
            })
          } else if (frame?.payload?.type === 'question/resolved') {
            // The question was answered (or cancelled) somewhere else — the
            // browser, another desktop tab, or this very plugin's own answer.
            // In every case the pet bubble must not stay open, so tell the
            // helper to tear it down. Frame's questionRpcId is the same rpcId
            // the /api/respond POST echoes, so match by that too.
            const sessionId = String(frame.payload.sessionId ?? '')
            const questionRpcId = String(frame.payload.questionRpcId ?? '')
            const pending = pendingQuestionsBySession.get(sessionId)
            if (pending !== undefined && (questionRpcId === '' || String(pending.rpcId) === questionRpcId)) {
              bridge?.send(createMessage(CompanionMessageKind.QUESTION_CLOSE, {
                sessionId,
                questionRpcId,
                outcome: frame.payload.outcome,
              }))
              pendingQuestionsBySession.delete(sessionId)
            }
          }
        } catch {
          // Non-JSON frames are ignored.
        }
      })
      socket.addEventListener('error', (event) => {
        if (muxSocket !== socket) return
        logger.warn?.(`dsh-dafeiyu mux error: ${event?.message ?? 'websocket error'}`)
      })
      socket.addEventListener('close', () => {
        if (muxSocket !== socket) return
        muxSocket = undefined
        if (muxRetryTimer || muxRetryCount >= 10) return
        muxRetryCount += 1
        // A dropped stream must not silently disable desktop Q&A: reconnect
        // with a short backoff until the downlink is stable again.
        muxRetryTimer = setTimeout(() => {
          muxRetryTimer = undefined
          void startMux()
        }, Math.min(1000 * muxRetryCount, 8000))
        muxRetryTimer.unref?.()
      })
    } catch (error) {
      logger.warn?.(`dsh-dafeiyu mux connect failed: ${error.message}`)
    }
  }

  const stopMux = () => {
    if (muxRetryTimer) clearTimeout(muxRetryTimer)
    muxRetryTimer = undefined
    const socket = muxSocket
    muxSocket = undefined
    if (socket) {
      try { socket.close() } catch { /* already closing */ }
    }
  }

  const handleQuestionReply = async (reply) => {
    const { sessionId, callId, answer, skip } = reply
    if (skip === true) {      if (sessionId !== undefined) pendingQuestionsBySession.delete(String(sessionId))
      return
    }
    const pending = sessionId !== undefined ? pendingQuestionsBySession.get(String(sessionId)) : undefined
    if (pending === undefined) {
      logger.warn?.(`dsh-dafeiyu no pending question for session ${sessionId}`)
      return
    }
    const sessionIdStr = String(sessionId)
    const answers = (answer ?? []).map((a) => ({
      id: String(a.id ?? ''),
      selected: Array.isArray(a.selected) ? a.selected.map((s) => String(s)) : [],
      ...(a.custom !== undefined ? { custom: String(a.custom) } : {}),
    }))
    try {
      const body = JSON.stringify({
        type: 'client-response',
        rpcId: pending.rpcId,
        result: {
          ok: true,
          value: { sessionId: sessionIdStr, answer: { answers } },
        },
      })
      const post = async (cookie) => {
        const headers = { 'content-type': 'application/json' }
        if (cookie !== undefined) headers.cookie = cookie
        return fetch(`${baseUrlOf()}/api/respond`, { method: 'POST', headers, body })
      }
      let response = await post(await getWebSessionCookie())
      if (response.status === 401) {
        // The cached cookie may be stale (host restarted, token rotated):
        // discard it and mint one fresh cookie on this same answer.
        webSessionCookie = undefined
        response = await post(await getWebSessionCookie())
      }
      if (response.ok) {
        pendingQuestionsBySession.delete(sessionIdStr)
        logger.info?.('dsh-dafeiyu answered question', { sessionId: sessionIdStr, callId })
      } else {
        logger.warn?.(`dsh-dafeiyu respond failed: ${response.status}`)
      }
    } catch (error) {
      logger.warn?.(`dsh-dafeiyu respond error: ${error.message}`)
    }
  }

  // The helper's right-click size menu persists its choice through this host
  // round-trip: write scale/bubbleScale back to the plugin settings so the
  // size survives a restart.
  const handleSettingsConfig = (reply) => {
    const patch = {}
    if (typeof reply.scale === 'number') patch.scale = reply.scale
    if (typeof reply.bubbleScale === 'number') patch.bubbleScale = reply.bubbleScale
    if (Object.keys(patch).length === 0) return
    void settings.update(patch).then(() => {
      logger.info?.('dsh-dafeiyu persisted size change', patch)
    }).catch((error) => {
      logger.warn?.(`dsh-dafeiyu size persist failed: ${error.message}`)
    })
  }

  const startRuntime = async (resolved) => {
    if (resolved.enabled === false) {
      logger.info?.('dsh-dafeiyu is disabled')
      return
    }
    const helperConfig = config.helper ?? {}
    const helperTemp = helperTempDir()
    try {
      mkdirSync(helperTemp, { recursive: true })
    } catch (error) {
      logger.warn?.(`dsh-dafeiyu helper temp dir failed: ${error.message}`)
    }
    const apiKey = await resolveApiKey()
    if (apiKey === undefined) scheduleApiKeyRetry()
    bridge = new HelperProcess({
      ...helperConfig,
      env: {
        ...helperConfig.env,
        // The one-file bootloader extracts itself; point it at a directory the
        // helper can always write even when the inherited TEMP is unusable.
        TEMP: helperTemp,
        TMP: helperTemp,
        DSH_DAFEIYU_SCALE: String(resolved.scale ?? defaults.scale),
        DSH_DAFEIYU_BUBBLE_SCALE: String(resolved.bubbleScale ?? defaults.bubbleScale),
        DSH_DAFEIYU_ACTIVITY_LEVEL: String(resolved.activityLevel ?? defaults.activityLevel),
        DSH_DAFEIYU_REDUCED_MOTION: resolved.reducedMotion === true ? '1' : '0',
        DSH_DAFEIYU_USE_SEPARATE_CARD: resolved.useSeparateCard === false ? '0' : '1',
        DSH_DAFEIYU_SHOW_STATS: resolved.showStats === false ? '0' : '1',
        DSH_DAFEIYU_BALANCE_CAP_CNY: String(resolved.balanceCapCny ?? defaults.balanceCapCny),
        DSH_DAFEIYU_ACTION_COOLDOWN_MS: String(resolved.actionCooldownMs ?? defaults.actionCooldownMs),
        DSH_DAFEIYU_ACTION_DWELL_MS: String(resolved.actionDwellMs ?? defaults.actionDwellMs),
        ...(apiKey === undefined ? {} : { DSH_DAFEIYU_API_KEY: apiKey }),
        // Explicitly hand the web URL to the helper so its "open in browser"
        // escape hatch can raise/activate the DSH page.
        DSH_WEB_URL: baseUrlOf(),
      },
      onQuestionReply: handleQuestionReply,
      onSettingsConfig: handleSettingsConfig,
    }, logger)
    reducer = new CompanionReducer({ includeSubagents: resolved.includeSubagents === true })
    bridge.start()
    bridge.send(createMessage(CompanionMessageKind.HELLO, {
      state: CompanionState.IDLE,
      host: 'deepseek-harness',
      pluginVersion: '0.1.0-alpha.7',
      message: 'BigFish connected to DSH',
    }))
    bridge.send(createMessage(CompanionMessageKind.STATE, {
      state: CompanionState.IDLE,
      phase: 'plugin-start',
      stage: '等待任务',
      message: '我在这儿等新任务哦',
      detail: 'DSH · 等待下一次任务',
    }))
    logger.info?.('dsh-dafeiyu companion bridge started')
    startStatsLoop()
  }

  void startRuntime(settings.get())

  // The companion intentionally observes every DSH session. Loader entries may
  // live inside a scoped composition, so use the unscoped root bus and dispose
  // the registrations explicitly with this plugin's lifecycle.
  const offEvent = eventCtx.on('session/event', (session, event) => {
    if (event?.type === 'turn/end') scheduleStatsRefresh()
    if (!bridge || !reducer) return
    for (const message of reducer.handle(session, event)) bridge.send(message)
  }, { global: true })
  const offDisposed = eventCtx.on('session/disposed', (session) => {
    if (!bridge || !reducer) return
    for (const message of reducer.disposeSession(session)) bridge.send(message)
  }, { global: true })

  let lastStatSettings = ''
  const statSettingsKey = (next) =>
    `${next.showStats !== false}|${next.balanceCapCny ?? defaults.balanceCapCny}`

  const unwatch = settings.watch((next) => {
    // Disabling is the only path that tears the helper down.  Every other
    // setting is applied live through a CONFIG message, so sliders never
    // restart the pet.  Starting a previously-disabled runtime is debounced
    // to avoid spawning repeatedly while settings settle.
    if (next.enabled === false) {
      if (restartTimer) {
        clearTimeout(restartTimer)
        restartTimer = undefined
      }
      stopRuntime('settings-change')
      return
    }
    if (!bridge) {
      scheduleRestart(next)
      return
    }
    if (restartTimer) {
      clearTimeout(restartTimer)
      restartTimer = undefined
    }
    applyLiveSettings(next)
    const key = statSettingsKey(next)
    if (key !== lastStatSettings) {
      lastStatSettings = key
      void pushStats('settings', true)
    }
  })
  if (typeof ctx.inject === 'function') {
    ctx.inject(['webServer'], (httpCtx) => {
      httpCtx.effect(
        () => httpCtx.webServer.register({ kind: 'exact', path: CONFIG_ENDPOINT, handler: createConfigHandler(settings) }),
        'dsh-dafeiyu: local settings endpoint',
      )
      httpCtx.effect(
        () => httpCtx.webServer.register({
          kind: 'exact',
          path: STATS_ENDPOINT,
          handler: async (req, res) => {
            if (!isLoopback(req.socket?.remoteAddress)) {
              jsonResponse(res, 403, { error: 'local access only' })
              return
            }
            if (req.method !== 'GET') {
              jsonResponse(res, 405, { error: 'method not allowed' })
              return
            }
            await pushStats('panel', true)
            const payload = latestStats ?? { updatedAt: Date.now() }
            jsonResponse(res, 200, {
              ...payload,
              todayLabel: formatCny(payload.todayCny),
              monthLabel: formatCny(payload.monthCny),
              balanceLabel: formatCny(payload.balanceCny),
            })
          },
        }),
        'dsh-dafeiyu: local stats endpoint',
      )
      // The mux stream is served by the same webserver; subscribe once it is up.
      httpCtx.effect(
        () => {
          startMux()
          return stopMux
        },
        'dsh-dafeiyu: mux question listener',
      )
    })
  }
  ctx.effect(() => () => {
    if (restartTimer) clearTimeout(restartTimer)
    restartTimer = undefined
    if (apiKeyRetryTimer) clearTimeout(apiKeyRetryTimer)
    apiKeyRetryTimer = undefined
    offEvent?.()
    offDisposed?.()
    unwatch()
    stopMux()
    stopStatsLoop()
    stopRuntime('dsh-host-stop')
  })
}

export function apply(ctx, config = {}) {
  if (typeof ctx.inject === 'function') {
    ctx.inject(['settings'], (settingsCtx) => mount(settingsCtx, config, ctx))
    return
  }
  mount(ctx, config)
}

export {
  CompanionMessageKind,
  CompanionReducer,
  CompanionState,
  HelperProcess,
}
