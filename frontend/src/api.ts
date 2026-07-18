import type {
  BrainUpdateResult, Explanation, Finding, GraphPoint, JobStatus,
  SourceView, Verdict, VerdictKind,
} from './types'

/* The console runs in two modes:
   - live: the local Python server (app.py) answers /api/*
   - static: Netlify demo build — practice-case data from /data/*.json,
     verdicts in localStorage, report generated client-side.
   Mode is detected on the first findings() call and cached. */
let staticMode = false
const VERDICTS_KEY = 'fraudmind_verdicts'

export function isStaticMode(): boolean {
  return staticMode
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(detail.detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

function localVerdicts(): Record<string, Verdict> {
  try {
    return JSON.parse(localStorage.getItem(VERDICTS_KEY) ?? '{}')
  } catch {
    return {}
  }
}

const DEMO_ONLY =
  'This public build is a read-only demo of the practice case. '
  + 'Run the local console (python3 app.py) to analyze new dossiers.'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatReply {
  reply: string
  engine: string
}

export const api = {
  chat: async (messages: ChatMessage[]): Promise<ChatReply> => {
    if (staticMode) return { reply: DEMO_ONLY, engine: 'none' }
    return postJSON<ChatReply>('/api/chat', { messages })
  },
  findings: async (): Promise<Finding[]> => {
    try {
      const res = await fetch('/api/findings')
      if (res.ok
        && res.headers.get('content-type')?.includes('json')) {
        return res.json() as Promise<Finding[]>
      }
    } catch {
      /* fall through to static data */
    }
    staticMode = true
    return getJSON<Finding[]>('/data/findings.json')
  },

  explanations: () => staticMode
    ? getJSON<Record<string, Explanation>>('/data/explanations.json')
    : getJSON<Record<string, Explanation>>('/api/explanations'),

  graph: () => staticMode
    ? getJSON<GraphPoint[]>('/data/graph.json')
    : getJSON<GraphPoint[]>('/api/graph'),

  verdicts: async (): Promise<Record<string, Verdict>> => staticMode
    ? localVerdicts()
    : getJSON<Record<string, Verdict>>('/api/verdicts'),

  status: () => getJSON<JobStatus>('/api/status'),

  source: async (ref: string): Promise<SourceView> => {
    if (staticMode) {
      return { ref, error: 'Source viewer needs the local console '
        + '(python3 app.py) — the public demo ships without the dossier.' }
    }
    const res = await fetch(`/api/source?ref=${encodeURIComponent(ref)}`)
    return res.json() as Promise<SourceView>
  },

  saveVerdict: async (id: string, verdict: VerdictKind, note: string) => {
    if (staticMode) {
      const all = {
        ...localVerdicts(),
        [id]: { verdict, note, at: new Date().toISOString().slice(0, 19).replace('T', ' ') },
      }
      localStorage.setItem(VERDICTS_KEY, JSON.stringify(all))
      return all
    }
    return postJSON<Record<string, Verdict>>('/api/verdicts',
      { id, verdict, note })
  },

  analyzePractice: async () => {
    if (staticMode) throw new Error(DEMO_ONLY)
    return postJSON<{ started: boolean }>('/api/analyze', {})
  },

  brainUpdate: async (): Promise<BrainUpdateResult> => {
    if (staticMode) {
      const verdicts = localVerdicts()
      const nodes = Object.values(verdicts).filter(
        (v) => v.verdict === 'confirmed' || v.verdict === 'followup').length
      return { nodes, cognee_pushed: false }
    }
    return postJSON<BrainUpdateResult>('/api/brain/update', {})
  },

  upload: async (files: File[]) => {
    if (staticMode) throw new Error(DEMO_ONLY)
    const fd = new FormData()
    for (const file of files) {
      const rel = (file as File & { webkitRelativePath?: string })
        .webkitRelativePath
      fd.append('files', file, rel && rel.length > 0 ? rel : file.name)
    }
    const res = await fetch('/api/upload', { method: 'POST', body: fd })
    if (!res.ok) {
      const detail = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(detail.detail ?? `HTTP ${res.status}`)
    }
    return res.json() as Promise<{ saved: number; started: boolean }>
  },

  downloadReport: async (
    findings: Finding[], verdicts: Record<string, Verdict>,
  ) => {
    if (!staticMode) {
      window.location.href = '/api/report'
      return
    }
    const md = clientReport(findings, verdicts)
    const url = URL.createObjectURL(
      new Blob([md], { type: 'text/markdown' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'fraudmind_report.md'
    a.click()
    URL.revokeObjectURL(url)
  },
}

const VERDICT_LABEL: Record<string, string> = {
  confirmed: 'CONFIRMED FRAUD', followup: 'FOLLOW-UP', dismissed: 'DISMISSED',
}

function clientReport(
  findings: Finding[], verdicts: Record<string, Verdict>,
): string {
  const confirmed = findings.filter(
    (f) => verdicts[f.id]?.verdict === 'confirmed')
  const total = confirmed.reduce((sum, f) => sum + (f.amount_eur ?? 0), 0)
  const lines = [
    '# fraudmind — Fraud Findings Report',
    '',
    `Generated ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`,
    '',
    `- Findings raised by engine: **${findings.length}**`,
    `- Reviewed by auditor: **${Object.keys(verdicts).length} / ${findings.length}**`,
    `- Confirmed fraud: **${confirmed.length}** (quantified impact **${total.toLocaleString('de-DE')} EUR**)`,
    '',
    'Every figure below is produced by the deterministic control engine and '
    + 'cites its source document. Verdicts are the human reviewer\'s.',
    '',
  ]
  for (const f of findings) {
    const v = verdicts[f.id]
    lines.push(`## ${f.id} — ${f.title}`)
    let meta = `**${f.tier}** · severity ${f.severity} · confidence ${Math.round(f.confidence * 100)}%`
    if (f.amount_eur) meta += ` · ${f.amount_eur.toLocaleString('de-DE')} EUR`
    lines.push(meta)
    lines.push(v
      ? `**Reviewer verdict: ${VERDICT_LABEL[v.verdict]}**${v.note ? ` — ${v.note}` : ''} (${v.at})`
      : '_Not yet reviewed._')
    lines.push('', f.explanation, '')
    lines.push('Provenance: ' + f.provenance.map((p) => `\`${p}\``).join('; '))
    lines.push('')
  }
  return lines.join('\n')
}

export function euro(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value.toLocaleString('de-DE', {
    style: 'currency', currency: 'EUR', maximumFractionDigits: 0,
  })
}
