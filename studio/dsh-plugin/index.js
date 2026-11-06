/**
 * dsh-garment-studio — DSH 侧薄壳插件（只做两件事，不含任何建模逻辑）
 *
 *   1. 在侧边栏提供一个面板：一个整页 iframe，指向本地 Garment Studio 服务
 *      （studio/server.py，默认 http://127.0.0.1:8765/）。设计师在那里看图、
 *      改描述、点确认、看纸样与布料仿真。
 *   2. 当有人在面板里点了「确认/修改」时，把这件事作为一条**普通用户消息**
 *      投回当前 DSH 会话，让模型接着生成 design.json 并跑构建。
 *
 * 为什么用「投消息」而不是让插件自己跑模型：描述 -> JSON 的推理属于会话能力，
 * 插件只负责把「人已确认」这个事实送回聊天；模型看到消息后按
 * docs/GC_STUDIO_SKILL.md 的步骤干活。中间状态全在磁盘（studio/jobs/<id>/），
 * 所以插件崩溃、DSH 重启都不丢东西。
 *
 * 所有状态都在仓库内：插件不写注册表、不装全局包，卸载 = 删目录 + 删 patch 条目。
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'garment-studio'
export const inject = ['webServer', 'sessionController']

const HERE = path.dirname(fileURLToPath(import.meta.url))

/**
 * 仓库根。插件被 install.ps1 复制进 ~/.dsh/profiles/web/node_modules/ 之后，
 * HERE 就不再是 studio/dsh-plugin 了，所以不能光靠 '..','..' 推。查找顺序：
 *   1) 同目录下的 repo.txt（install.ps1 复制时写死绝对路径）
 *   2) 从 HERE 向上找，哪个目录里有 studio/server.py 就是仓库根
 *   3) 开发时直接挂在 studio/dsh-plugin 下的情形
 *   4) 兜底：本机仓库的绝对路径
 */
function resolveRepoRoot() {
  try {
    const pinned = path.join(HERE, 'repo.txt')
    if (existsSync(pinned)) {
      const dir = readFileSync(pinned, 'utf8').trim()
      if (dir && existsSync(path.join(dir, 'studio', 'server.py'))) return dir
    }
  } catch { /* ignore */ }
  let dir = HERE
  for (let i = 0; i < 6; i += 1) {
    if (existsSync(path.join(dir, 'studio', 'server.py'))) return dir
    const up = path.dirname(dir)
    if (up === dir) break
    dir = up
  }
  const dev = path.resolve(HERE, '..', '..')
  if (existsSync(path.join(dev, 'studio', 'server.py'))) return dev
  return 'C:\\Users\\41239\\Desktop\\科研\\ChatGarment-main'
}
const REPO_ROOT = resolveRepoRoot()
const PANEL_ROUTE = '/garment-studio/panel'
const STATUS_ROUTE = '/garment-studio/status'
const REVEAL_ROUTE = '/garment-studio/reveal'
const POLL_MS = 2000

function readJson(file) {
  try {
    return JSON.parse(readFileSync(file, 'utf8'))
  } catch {
    return null
  }
}

/** 宿主 prompt 的第二个参数：0.2.1-rc.4 起是 MessageSource，更早是 AbortSignal。 */
function promptSource(request) {
  const source = { kind: 'user', rpcId: request.requestId }
  if (request.clientTimeZone) source.clientTimeZone = request.clientTimeZone
  return source
}

async function deliverPrompt(sc, request) {
  try {
    return await sc.prompt(request, promptSource(request))
  } catch (e) {
    const msg = String((e && e.message) || e)
    if (/throwIfAborted|AbortSignal|signal/i.test(msg)) {
      return await sc.prompt(request, new AbortController().signal)
    }
    throw e
  }
}

/** 面板 HTML：整页 iframe + 一行工具栏（刷新 / 新窗口打开）。 */
function panelHtml(panelUrl, jobCount, disabled) {
  const safe = panelUrl.replace(/"/g, '&quot;')
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Garment Studio</title>
<style>
  html,body{margin:0;height:100%;background:#0f1116;color:#c9d1d9;
    font:12px/1.5 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  .bar{display:flex;gap:10px;align-items:center;padding:6px 10px;
    background:#151922;border-bottom:1px solid #232a36}
  .bar b{font-weight:600;color:#e6edf3}
  .bar .sp{flex:1}
  .bar a,.bar button{color:#9ecbff;background:none;border:1px solid #2b3444;
    border-radius:6px;padding:3px 8px;text-decoration:none;cursor:pointer;font-size:12px}
  .bar a:hover,.bar button:hover{background:#1d2431}
  iframe{display:block;width:100%;height:calc(100% - 33px);border:0;background:#0f1116}
</style></head>
<body>
<div class="bar">
  <b>Garment Studio</b>
  <span>作业 ${jobCount} 个</span>
  ${disabled ? '<span style="color:#f0b36b">面板服务未启动：在仓库里跑 .venv/Scripts/python.exe -m studio.server --port 8765</span>' : ''}
  <span class="sp"></span>
  <button onclick="document.getElementById('f').src=document.getElementById('f').src">刷新面板</button>
  <a href="${safe}" target="_blank" rel="noreferrer">新窗口打开</a>
</div>
<iframe id="f" src="${safe}" allow="clipboard-read; clipboard-write"></iframe>
<script>
// 内层面板在 http://127.0.0.1:8765，跨源不能直接调宿主路由；用 postMessage 中转。
// 宿主进程（DSH）运行在用户交互会话里，能真正拉起资源管理器——这是「打开文件夹」
// 在服务由沙箱 shell 启动时唯一可靠的路径。
addEventListener("message", async (ev) => {
  const d = ev.data || {}
  if (d.type !== "gcstudio-reveal") return
  let out = { type: "gcstudio-reveal-result", job: d.job, ok: false, error: "bad request" }
  try {
    const r = await fetch("/garment-studio/reveal?job=" + encodeURIComponent(d.job || ""),
      { cache: "no-store" })
    out = Object.assign(out, await r.json())
    out.type = "gcstudio-reveal-result"
    out.job = d.job
  } catch (e) { out.error = String(e && e.message || e) }
  ev.source && ev.source.postMessage(out, "*")
})
</script>
</body></html>`
}

export function apply(ctx, config = {}) {
  const panelUrl = String(config.panelUrl || 'http://127.0.0.1:8765/')
  const jobsRoot = String(config.jobsRoot || path.join(REPO_ROOT, 'studio', 'jobs'))
  const autoStart = config.autoStart !== false
  const seen = new Map() // job_id -> approval ts 已投递
  // 插件刚挂载时不去重放历史确认：只转发「本次挂载之后」发生的人工作业，
  // 否则每次重启 DSH 都会把旧作业再投一遍。
  const startedAt = Date.now() - 1000
  let child = null
  let timer = null
  let panelUp = false

  const log = (msg) => {
    try { ctx.logger?.info?.(`[garment-studio] ${msg}`) } catch { /* no logger */ }
  }

  async function ping() {
    try {
      const res = await fetch(panelUrl.replace(/\/$/, '') + '/api/health', { signal: AbortSignal.timeout(1500) })
      return res.ok
    } catch {
      return false
    }
  }

  /** 面板服务没起来就替用户拉起来（和手动起服务完全一样，只是省一次命令）。 */
  async function ensurePanel() {
    if (await ping()) { panelUp = true; return }
    panelUp = false
    if (!autoStart || child) return
    const py = [
      path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe'),
      path.join(REPO_ROOT, '.venv', 'bin', 'python'),
    ].find((p) => existsSync(p))
    if (!py) return
    try {
      child = spawn(py, ['-m', 'studio.server', '--port', '8765'], {
        cwd: REPO_ROOT, stdio: 'ignore', windowsHide: true, detached: false,
      })
      child.on('exit', () => { child = null })
      log('started studio server: ' + py)
    } catch (e) {
      child = null
      log('无法启动 studio server: ' + (e && e.message))
    }
  }

  function listJobs() {
    try {
      return readdirSync(jobsRoot).filter((d) => {
        try { return statSync(path.join(jobsRoot, d)).isDirectory() } catch { return false }
      })
    } catch {
      return []
    }
  }

  /**
   * 每 2 秒扫一次 approval.json。发现新的确认就把消息投回它自己的会话。
   * 用轮询而不是 fs.watch：作业目录在 Windows 上会被其他进程反复 rename，
   * watch 会丢事件；2 秒的延迟对「人点完确认，模型开始生成」完全够用。
   */
  async function pollApprovals() {
    for (const jobId of listJobs()) {
      const jdir = path.join(jobsRoot, jobId)
      const approval = readJson(path.join(jdir, 'approval.json'))
      if (!approval || !approval.ts) continue
      if (seen.get(jobId) === approval.ts) continue
      seen.set(jobId, approval.ts)
      const approvedMs = Date.parse(approval.ts)
      if (Number.isFinite(approvedMs) && approvedMs < startedAt) continue
      const request = readJson(path.join(jdir, 'request.json')) || {}
      const sessionId = request.session_id
      const decision = approval.decision === 'edit' ? '按我改的来' : '没问题'
      const text = String(approval.text || '').trim()
      const body = [
        `【Garment Studio】作业 ${jobId} 的服装描述已由人工确认（${decision}）。`,
        `工作目录：${jdir}`,
        text ? `确认后的描述全文（以 approval.json 为准）：\n${text}` : '',
        '请按 docs/GC_STUDIO_SKILL.md 的步骤：读描述 -> 写 design.json -> 跑',
        `  ./.venv/Scripts/python.exe -m studio.job_runner "${jobId}"`,
        '-> 构建失败就按提示微调浮点重试（最多 2 次）-> 把结果（纸样/仿真/是否成功）告诉我。',
      ].filter(Boolean).join('\n')

      if (!sessionId) { log('跳过投递（作业没有 session_id）: ' + jobId); continue }
      try {
        const sc = ctx.sessionController
        const requestId = 'gcstudio-' + approval.ts.replace(/[^0-9]/g, '') + '-' + Math.random().toString(36).slice(2, 6)
        await deliverPrompt(sc, {
          requestId, sessionId, mode: 'queue',
          content: [{ type: 'text', text: body }],
        })
        log('relayed approval of ' + jobId + ' to session ' + sessionId)
      } catch (e) {
        log('投递失败 ' + jobId + ': ' + (e && e.message || e))
      }
    }
  }

  ctx.effect(() => {
    const offs = []
    const routes = [
      [PANEL_ROUTE, async (req, res) => {
        const jobs = listJobs().length
        res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' })
        res.end(panelHtml(panelUrl, jobs, !panelUp))
      }],
      [REVEAL_ROUTE, async (req, res) => {
        // Open a job folder in Explorer. The panel calls this when the Python server
        // reports that it could not launch a window (a sandboxed shell has no usable
        // window station: os.startfile raises WinError 5 and explorer exits 0xC0000142).
        const send = (code, obj) => {
          res.writeHead(code, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
          res.end(JSON.stringify(obj))
        }
        let job = ''
        try { job = new URL(req.url || '/', 'http://localhost').searchParams.get('job') || '' } catch { /* keep '' */ }
        if (!job || /[\\/:*?"<>|]/.test(job) || job === '.' || job === '..') return send(400, { ok: false, error: 'bad job name' })
        const dir = path.resolve(jobsRoot, job)
        if (!dir.startsWith(path.resolve(jobsRoot) + path.sep) || !existsSync(dir)) {
          return send(404, { ok: false, error: 'no such job folder: ' + dir })
        }
        try {
          const proc = spawn('explorer.exe', [dir], { detached: true, stdio: 'ignore', windowsHide: false })
          proc.unref()
          log('reveal ' + job + ' via explorer.exe')
          return send(200, { ok: true, path: dir, method: 'explorer' })
        } catch (e) {
          return send(500, { ok: false, error: String(e && e.message || e) })
        }
      }],
      [STATUS_ROUTE, async (req, res) => {
        const jobs = listJobs()
        const approvals = jobs.filter((j) => existsSync(path.join(jobsRoot, j, 'approval.json')))
        res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
        res.end(JSON.stringify({ ok: true, panel: { url: panelUrl, up: panelUp },
          jobs: jobs.length, approvals: approvals.length }))
      }],
    ]
    for (const [p, h] of routes) {
      try {
        offs.push(ctx.webServer.register({ kind: 'exact', path: p, handler: h }))
      } catch (e) {
        log('路由被占用 ' + p + ': ' + (e && e.message))
      }
    }

    void ensurePanel()
    timer = setInterval(() => { void pollApprovals() }, POLL_MS)
    if (timer.unref) timer.unref()

    return () => {
      for (const off of offs) { try { off() } catch { /* ignore */ } }
      if (timer) { clearInterval(timer); timer = null }
      if (child) { try { child.kill() } catch { /* ignore */ } child = null }
    }
  })
}
