import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { apply, name, inject } from './index.js'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const JOBS = path.resolve(HERE, '..', '..', 'studio', 'jobs')

const calls = []
const ctx = {
  logger: { info: (m) => calls.push(['info', m]), warn: (m) => calls.push(['warn', m]) },
  sessionController: { prompt: async (req, src) => { calls.push(['prompt', req.sessionId, req.content[0].text.slice(0, 40), src.kind]); return { accepted: true } } },
  webServer: { register: ({ path: p }) => { calls.push(['route', p]); return () => {} } },
  effect: (fn) => fn(),
}
apply(ctx, { autoStart: false, panelUrl: 'http://127.0.0.1:8765/' })

const job = 'selftest-' + Date.now()
const dir = path.join(JOBS, job)
mkdirSync(dir, { recursive: true })
writeFileSync(path.join(dir, 'request.json'), JSON.stringify({ job_id: job, session_id: 'sess-live' }))
writeFileSync(path.join(dir, 'approval.json'), JSON.stringify({ decision: 'accept', text: '一条短裙', ts: new Date().toISOString() }))
await new Promise((r) => setTimeout(r, 2600))
rmSync(dir, { recursive: true, force: true })
console.log(JSON.stringify({ name, inject, calls }, null, 1))
process.exit(0)
